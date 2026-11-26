from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import httpx
from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    Message,
    MessageSendParams,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)

from knowledge_agent.config import Settings
from knowledge_agent.executor import (
    DEADLINE_MESSAGE,
    ERROR_MESSAGES,
    KnowledgeSearchExecutor,
)
from knowledge_agent.lcore_client import (
    EvidenceStatus,
    LcoreError,
    LcoreErrorKind,
    LcoreEvidence,
    LcoreResult,
)
from knowledge_agent.server import create_app

GOOD_ANSWER = (
    "An OpenShift route exposes a service at a host name so external clients "
    "can reach it."
)


def _settings(**overrides: str) -> Settings:
    env = {
        "LCORE_AGENT_CARD_URL": (
            "http://lcore.test/.well-known/agent-card.json"
        )
    }
    env.update(overrides)
    return Settings.from_env(env)


def _result(
    text: str = GOOD_ANSWER,
    *,
    status: EvidenceStatus = "unavailable",
    evidence: Sequence[LcoreEvidence] = (),
    context_id: str = "lcore-ctx-1",
) -> LcoreResult:
    return LcoreResult(
        text=text,
        task_id="lcore-task",
        context_id=context_id,
        evidence=tuple(evidence),
        evidence_status=status,
    )


class FakeSearchClient:
    def __init__(
        self,
        results: Sequence[LcoreResult | Exception | tuple[LcoreResult, float]],
        *,
        gate: asyncio.Event | None = None,
    ) -> None:
        self._results = list(results)
        self._gate = gate
        self.calls: list[tuple[str, str | None]] = []

    async def search(
        self, query: str, *, context_id: str | None = None
    ) -> LcoreResult:
        self.calls.append((query, context_id))
        if self._gate is not None:
            await self._gate.wait()
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            result, delay = item
            await asyncio.sleep(delay)
            return result
        return item


def _message(text: str):
    return Message(
        role=Role.user,
        parts=[Part(root=TextPart(text=text))],
        message_id=str(uuid.uuid4()),
    )


def _payload(
    text: str,
    *,
    task_id: str | None = None,
    context_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "kind": "message",
        "role": "user",
        "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": text}],
    }
    if task_id is not None:
        message["taskId"] = task_id
    if context_id is not None:
        message["contextId"] = context_id
    if metadata is not None:
        message["metadata"] = metadata
    params: dict[str, Any] = {"message": message}
    if metadata is not None:
        params["metadata"] = metadata
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": params,
    }


@asynccontextmanager
async def _client(
    settings: Settings, fake: FakeSearchClient
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, search_client=fake)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client


def _artifact_text(task: dict[str, Any]) -> str:
    return "\n".join(
        part["text"]
        for artifact in task.get("artifacts", [])
        for part in artifact["parts"]
    )


def _artifact_metadata(task: dict[str, Any]) -> dict[str, Any]:
    assert task["artifacts"]
    return task["artifacts"][0].get("metadata", {}).get("knowledge_agent", {})


async def _drain(queue: EventQueue) -> list[Any]:
    events: list[Any] = []
    while True:
        try:
            events.append(await queue.dequeue_event(no_wait=True))
        except asyncio.QueueEmpty:
            return events


def _final_state(events: Sequence[Any]) -> TaskState:
    states = [
        event.status.state
        for event in events
        if isinstance(event, TaskStatusUpdateEvent)
    ]
    assert states
    return states[-1]


async def test_greeting_requests_clarification_without_search() -> None:
    fake = FakeSearchClient([])

    async with _client(_settings(), fake) as client:
        body = (await client.post("/a2a", json=_payload("hello"))).json()

    task = body["result"]
    assert task["status"]["state"] == "input-required"
    assert task["status"]["message"]["parts"][0]["text"] == (
        "What would you like to search for?"
    )
    assert task["metadata"]["knowledge_agent"]["phase"] == (
        "awaiting_clarification"
    )
    assert fake.calls == []


async def test_clarification_reply_runs_the_search() -> None:
    fake = FakeSearchClient([_result()])

    async with _client(_settings(), fake) as client:
        first = (await client.post("/a2a", json=_payload("hello"))).json()
        task = first["result"]
        second = (
            await client.post(
                "/a2a",
                json=_payload(
                    "How do OpenShift routes expose services?",
                    task_id=task["id"],
                    context_id=task["contextId"],
                ),
            )
        ).json()

    result = second["result"]
    assert result["status"]["state"] == "completed"
    assert len(fake.calls) == 1
    query, context_id = fake.calls[0]
    assert query.startswith("How do OpenShift routes expose services?")
    assert "Original question: hello" in query
    assert context_id is None
    assert GOOD_ANSWER in _artifact_text(result)


async def test_gap_answer_triggers_one_follow_up() -> None:
    fake = FakeSearchClient(
        [
            _result("I don't know.", status="unavailable"),
            _result(GOOD_ANSWER, status="unavailable", context_id="lcore-ctx-2"),
            _result(
                "Consolidated route answer.",
                status="unavailable",
                context_id="lcore-ctx-2",
            ),
        ]
    )

    async with _client(_settings(), fake) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "completed"
    assert len(fake.calls) == 3
    assert fake.calls[1][1] == "lcore-ctx-1"
    consolidation_query, consolidation_context = fake.calls[2]
    assert "You are consolidating documentation-search results" in (
        consolidation_query
    )
    assert "[Search result 1]" in consolidation_query
    assert "[Search result 2]" in consolidation_query
    assert consolidation_context == "lcore-ctx-2"
    metadata = _artifact_metadata(task)
    assert metadata["searches"] == 2
    assert metadata["follow_up"] == "performed"
    assert metadata["evidence_status"] == "unavailable"
    assert metadata["consolidation"] == "llm"
    assert "Consolidated route answer." in _artifact_text(task)


async def test_failed_consolidation_falls_back_to_deterministic_answer() -> None:
    fake = FakeSearchClient(
        [
            _result("I don't know.", status="unavailable"),
            _result(GOOD_ANSWER, status="unavailable", context_id="lcore-ctx-2"),
            LcoreError(LcoreErrorKind.TIMEOUT, "LCORE request timed out"),
        ]
    )

    async with _client(_settings(), fake) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "completed"
    metadata = _artifact_metadata(task)
    assert metadata["consolidation"] == "fallback"
    assert GOOD_ANSWER in _artifact_text(task)


async def test_empty_consolidation_falls_back_to_deterministic_answer() -> None:
    fake = FakeSearchClient(
        [
            _result("I don't know.", status="unavailable"),
            _result(GOOD_ANSWER, status="unavailable", context_id="lcore-ctx-2"),
            _result("   ", status="unavailable", context_id="lcore-ctx-2"),
        ]
    )

    async with _client(_settings(), fake) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "completed"
    metadata = _artifact_metadata(task)
    assert metadata["consolidation"] == "fallback"
    assert GOOD_ANSWER in _artifact_text(task)


async def test_upstream_error_fails_task_without_retry() -> None:
    fake = FakeSearchClient(
        [LcoreError(LcoreErrorKind.TIMEOUT, "LCORE request timed out")]
    )

    async with _client(_settings(), fake) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "failed"
    assert task["status"]["message"]["parts"][0]["text"] == (
        ERROR_MESSAGES[LcoreErrorKind.TIMEOUT]
    )
    assert task["metadata"]["knowledge_agent"]["error"] == "timeout"
    assert len(fake.calls) == 1


async def test_caller_metadata_does_not_reach_upstream() -> None:
    fake = FakeSearchClient([_result()])
    metadata = {
        "vector_store_ids": ["caller-selected"],
        "model": "caller/model",
        "provider": "caller",
    }

    async with _client(_settings(), fake) as client:
        body = (
            await client.post(
                "/a2a",
                json=_payload(
                    "How do OpenShift routes work?", metadata=metadata
                ),
            )
        ).json()

    assert body["result"]["status"]["state"] == "completed"
    assert [call[0] for call in fake.calls] == [
        "How do OpenShift routes work?"
    ]


async def test_evidence_is_reported_in_text_and_metadata() -> None:
    evidence = (
        LcoreEvidence(
            kind="document",
            title="Route concepts",
            url="https://docs.example/routes",
            document_id="doc-1",
        ),
    )
    fake = FakeSearchClient([_result(status="available", evidence=evidence)])

    async with _client(_settings(), fake) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    text = _artifact_text(task)
    assert "Sources:" in text
    assert "Route concepts" in text
    metadata = _artifact_metadata(task)
    assert metadata["evidence_status"] == "available"
    assert metadata["evidence"][0]["document_id"] == "doc-1"
    assert metadata["follow_up"] == "not_needed"


async def test_unavailable_evidence_is_labeled_unverified() -> None:
    fake = FakeSearchClient([_result(status="unavailable")])

    async with _client(_settings(), fake) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    assert "this answer is unverified" in _artifact_text(body["result"])


async def test_saturated_capacity_is_rejected() -> None:
    settings = _settings(
        WORKFLOW_TASK_DEADLINE_SECONDS="1",
        WORKFLOW_UPSTREAM_TIMEOUT_SECONDS="1",
    )
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    fake = FakeSearchClient([])
    executor = KnowledgeSearchExecutor(settings, fake, semaphore=semaphore)
    queue = EventQueue()
    context = RequestContext(
        request=MessageSendParams(message=_message("How do routes work?"))
    )

    await executor.execute(context, queue)

    events = await _drain(queue)
    assert _final_state(events) is TaskState.rejected
    assert fake.calls == []


async def test_deadline_fails_when_no_result_exists() -> None:
    settings = _settings(
        WORKFLOW_TASK_DEADLINE_SECONDS="1",
        WORKFLOW_UPSTREAM_TIMEOUT_SECONDS="1",
    )
    fake = FakeSearchClient([(_result(), 2.0)])
    executor = KnowledgeSearchExecutor(settings, fake)
    queue = EventQueue()
    context = RequestContext(
        request=MessageSendParams(message=_message("How do routes work?"))
    )

    await executor.execute(context, queue)

    events = await _drain(queue)
    assert _final_state(events) is TaskState.failed
    message = events[-1].status.message
    assert message is not None
    assert message.parts[0].root.text == DEADLINE_MESSAGE


async def test_deadline_returns_first_answer_with_limitation() -> None:
    settings = _settings(
        WORKFLOW_TASK_DEADLINE_SECONDS="1",
        WORKFLOW_UPSTREAM_TIMEOUT_SECONDS="1",
    )
    fake = FakeSearchClient(
        [(_result("I don't know.", status="unavailable"), 0.0), (_result(), 2.0)]
    )
    executor = KnowledgeSearchExecutor(settings, fake)
    queue = EventQueue()
    context = RequestContext(
        request=MessageSendParams(message=_message("How do routes work?"))
    )

    await executor.execute(context, queue)

    events = await _drain(queue)
    assert _final_state(events) is TaskState.completed
    artifact = next(
        event for event in events if isinstance(event, TaskArtifactUpdateEvent)
    )
    part = artifact.artifact.parts[0].root
    assert isinstance(part, TextPart)
    text = part.text
    assert "I don't know." in text
    assert "workflow deadline was reached" in text
    metadata = artifact.artifact.metadata
    assert metadata is not None
    assert metadata["knowledge_agent"]["follow_up"] == "skipped_limit"

