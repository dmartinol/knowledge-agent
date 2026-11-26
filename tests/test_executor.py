from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
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
from pydantic_ai.exceptions import ModelTimeoutError, UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from knowledge_agent.config import Settings
from knowledge_agent.executor import (
    AGENT_ERROR_MESSAGES,
    DEADLINE_MESSAGE,
    LCORE_ERROR_MESSAGES,
    KnowledgeSearchExecutor,
)
from knowledge_agent.lcore_client import (
    EvidenceStatus,
    LcoreError,
    LcoreErrorKind,
    LcoreEvidence,
    LcoreResult,
)
from knowledge_agent.reasoning import AgentErrorKind
from knowledge_agent.server import create_app

GOOD_ANSWER = (
    "An OpenShift route exposes a service at a host name so external clients "
    "can reach it."
)
CLARIFICATION_QUESTION = "Which OpenShift component do you mean?"

SyncStep = Callable[[list[ModelMessage], AgentInfo], ModelResponse]
AsyncStep = Callable[[list[ModelMessage], AgentInfo], Awaitable[ModelResponse]]
Step = SyncStep | AsyncStep


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
) -> LcoreResult:
    return LcoreResult(
        text=text,
        task_id="lcore-task",
        context_id="lcore-context",
        evidence=tuple(evidence),
        evidence_status=status,
    )


class FakeSearchClient:
    def __init__(
        self,
        results: Sequence[LcoreResult | Exception | tuple[LcoreResult, float]],
    ) -> None:
        self._results = list(results)
        self.calls: list[str] = []

    async def search(self, query: str) -> LcoreResult:
        self.calls.append(query)
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            result, delay = item
            await asyncio.sleep(delay)
            return result
        return item


def _tool(query: str) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart("search_knowledge", {"query": query})]
    )


def _clarify(question: str) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                "final_result_ClarificationRequest",
                {"kind": "clarification", "question": question},
            )
        ]
    )


def _answer(text: str = GOOD_ANSWER, gaps: Sequence[str] = ()) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                "final_result_KnowledgeAnswer",
                {"kind": "answer", "answer": text, "gaps": list(gaps)},
            )
        ]
    )


def _model(*steps: ModelResponse | Step) -> FunctionModel:
    script = list(steps)

    async def run(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        if not script:
            raise UnexpectedModelBehavior("script exhausted")
        step = script.pop(0)
        if isinstance(step, ModelResponse):
            return step
        result = step(messages, info)
        if inspect.isawaitable(result):
            return await result
        return result

    return FunctionModel(run)


def _raises(exc: Exception) -> SyncStep:
    def run(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise exc

    return run


def _sleeps(seconds: float) -> AsyncStep:
    async def run(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        await asyncio.sleep(seconds)
        return _answer()

    return run


def _message(text: str) -> Message:
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
    settings: Settings,
    fake: FakeSearchClient,
    model: FunctionModel | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, search_client=fake, model=model)
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


async def test_model_decides_to_clarify_without_search() -> None:
    fake = FakeSearchClient([])
    model = _model(_clarify(CLARIFICATION_QUESTION))

    async with _client(_settings(), fake, model) as client:
        body = (await client.post("/a2a", json=_payload("hello"))).json()

    task = body["result"]
    assert task["status"]["state"] == "input-required"
    assert task["status"]["message"]["parts"][0]["text"] == (
        CLARIFICATION_QUESTION
    )
    metadata = task["metadata"]["knowledge_agent"]
    assert metadata["phase"] == "awaiting_clarification"
    assert metadata["question"] == "hello"
    assert fake.calls == []


async def test_clarification_reply_searches_and_answers() -> None:
    fake = FakeSearchClient([_result()])
    model = _model(
        _clarify(CLARIFICATION_QUESTION),
        _tool("OpenShift route to service exposure"),
        _answer(),
    )

    async with _client(_settings(), fake, model) as client:
        first = (await client.post("/a2a", json=_payload("routes?"))).json()
        task = first["result"]
        second = (
            await client.post(
                "/a2a",
                json=_payload(
                    "OpenShift routes",
                    task_id=task["id"],
                    context_id=task["contextId"],
                ),
            )
        ).json()

    result = second["result"]
    assert result["status"]["state"] == "completed"
    assert fake.calls == ["OpenShift route to service exposure"]
    metadata = _artifact_metadata(result)
    assert metadata["clarification_used"] is True
    assert metadata["searches"] == 1
    assert GOOD_ANSWER in _artifact_text(result)


async def test_second_clarification_fails_the_task() -> None:
    fake = FakeSearchClient([])
    model = _model(
        _clarify(CLARIFICATION_QUESTION),
        _clarify("Anything else?"),
        _clarify("Anything else?"),
        _clarify("Anything else?"),
    )

    async with _client(_settings(), fake, model) as client:
        first = (await client.post("/a2a", json=_payload("routes?"))).json()
        task = first["result"]
        second = (
            await client.post(
                "/a2a",
                json=_payload(
                    "OpenShift routes",
                    task_id=task["id"],
                    context_id=task["contextId"],
                ),
            )
        ).json()

    result = second["result"]
    assert result["status"]["state"] == "failed"
    assert result["metadata"]["knowledge_agent"]["error"] == (
        "model_output_invalid"
    )
    assert fake.calls == []


async def test_answer_before_search_is_retried_then_accepted() -> None:
    fake = FakeSearchClient([_result()])
    model = _model(_answer(), _tool("routes"), _answer())

    async with _client(_settings(), fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "completed"
    assert len(fake.calls) == 1


async def test_answer_with_sources_heading_fails_after_retries() -> None:
    fake = FakeSearchClient([_result()])
    sourced = f"{GOOD_ANSWER}\n\nSources:\n- https://docs.example"
    model = _model(_tool("routes"), _answer(sourced), _answer(sourced), _answer(sourced))

    async with _client(_settings(), fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "failed"
    assert task["status"]["message"]["parts"][0]["text"] == (
        AGENT_ERROR_MESSAGES[AgentErrorKind.MODEL_OUTPUT_INVALID]
    )
    assert task["metadata"]["knowledge_agent"]["error"] == (
        "model_output_invalid"
    )


async def test_answer_with_url_fails_after_retries() -> None:
    fake = FakeSearchClient([_result()])
    with_url = "See https://docs.example/routes for details."
    model = _model(_tool("routes"), _answer(with_url), _answer(with_url), _answer(with_url))

    async with _client(_settings(), fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    assert body["result"]["status"]["state"] == "failed"
    assert body["result"]["metadata"]["knowledge_agent"]["error"] == (
        "model_output_invalid"
    )


async def test_empty_answer_fails_after_retries() -> None:
    fake = FakeSearchClient([_result()])
    model = _model(_tool("routes"), _answer("   "), _answer("  "), _answer(" "))

    async with _client(_settings(), fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    assert body["result"]["status"]["state"] == "failed"


async def test_search_cap_adds_a_gap_and_metadata() -> None:
    fake = FakeSearchClient([_result()])
    settings = _settings(WORKFLOW_MAX_ROUNDS="1")
    model = _model(_tool("routes"), _tool("routes again"), _answer())

    async with _client(settings, fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "completed"
    assert len(fake.calls) == 1
    metadata = _artifact_metadata(task)
    assert metadata["searches"] == 1
    assert metadata["search_limit"] == 1
    assert metadata["limits_hit"] == ["search"]
    text = _artifact_text(task)
    assert "Gaps:" in text
    assert "search limit was reached" in text


async def test_upstream_error_fails_task_without_answering() -> None:
    fake = FakeSearchClient(
        [LcoreError(LcoreErrorKind.TIMEOUT, "LCORE request timed out")]
    )
    model = _model(_tool("routes"), _answer())

    async with _client(_settings(), fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "failed"
    assert task["status"]["message"]["parts"][0]["text"] == (
        LCORE_ERROR_MESSAGES[LcoreErrorKind.TIMEOUT]
    )
    assert task["metadata"]["knowledge_agent"]["error"] == "timeout"
    assert len(fake.calls) == 1


async def test_caller_metadata_does_not_reach_upstream() -> None:
    fake = FakeSearchClient([_result()])
    model = _model(_tool("OpenShift routes"), _answer())
    metadata = {
        "vector_store_ids": ["caller-selected"],
        "model": "caller/model",
        "provider": "caller",
    }

    async with _client(_settings(), fake, model) as client:
        body = (
            await client.post(
                "/a2a",
                json=_payload(
                    "How do OpenShift routes work?", metadata=metadata
                ),
            )
        ).json()

    assert body["result"]["status"]["state"] == "completed"
    assert fake.calls == ["OpenShift routes"]


async def test_retrieved_evidence_is_rendered_as_sources() -> None:
    evidence = (
        LcoreEvidence(
            kind="document",
            source="okp",
            document_id="doc-1",
            title="Route concepts",
            url="https://docs.example/routes",
            support="retrieved",
        ),
    )
    fake = FakeSearchClient([_result(status="available", evidence=evidence)])
    model = _model(_tool("routes"), _answer())

    async with _client(_settings(), fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    text = _artifact_text(task)
    assert "Sources:" in text
    assert "Route concepts" in text
    assert "https://docs.example/routes" in text
    metadata = _artifact_metadata(task)
    assert metadata["evidence_status"] == "available"
    assert metadata["evidence"][0] == {
        "search": 1,
        "source": "okp",
        "document_id": "doc-1",
        "title": "Route concepts",
        "url": "https://docs.example/routes",
        "support": "retrieved",
    }
    assert metadata["loop"] == "typed_tool"
    assert metadata["decision_source"] == "llm"
    assert "skills" not in metadata


async def test_cited_only_evidence_is_labeled_unverified() -> None:
    evidence = (
        LcoreEvidence(
            kind="document",
            source="okp",
            document_id="doc-1",
            title="Route concepts",
            support="cited",
        ),
    )
    fake = FakeSearchClient([_result(status="available", evidence=evidence)])
    model = _model(_tool("routes"), _answer())

    async with _client(_settings(), fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    text = _artifact_text(body["result"])
    assert "Sources:" not in text
    assert "Unverified" in text
    metadata = _artifact_metadata(body["result"])
    assert metadata["evidence"] == []


async def test_model_configuration_error_fails_task() -> None:
    fake = FakeSearchClient([])

    async with _client(_settings(), fake, None) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "failed"
    assert task["status"]["message"]["parts"][0]["text"] == (
        AGENT_ERROR_MESSAGES[AgentErrorKind.MODEL_CONFIG_ERROR]
    )
    assert task["metadata"]["knowledge_agent"]["error"] == (
        "model_config_error"
    )


async def test_unusable_skills_fail_task(tmp_path) -> None:
    fake = FakeSearchClient([_result()])
    model = _model(_tool("OpenShift routes"), _answer())
    settings = _settings(AGENT_SKILLS_DIR=str(tmp_path / "absent"))

    async with _client(settings, fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "failed"
    assert task["metadata"]["knowledge_agent"]["error"] == "skills_unavailable"
    assert fake.calls == []


async def test_model_timeout_fails_task() -> None:
    fake = FakeSearchClient([])
    model = _model(_raises(ModelTimeoutError("test-model", "timed out")))

    async with _client(_settings(), fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "failed"
    assert task["metadata"]["knowledge_agent"]["error"] == "model_timeout"


async def test_request_limit_fails_task() -> None:
    fake = FakeSearchClient([_result()])
    settings = _settings(AGENT_LLM_REQUEST_LIMIT="1")
    model = _model(_tool("routes"), _answer())

    async with _client(settings, fake, model) as client:
        body = (
            await client.post(
                "/a2a", json=_payload("How do OpenShift routes work?")
            )
        ).json()

    task = body["result"]
    assert task["status"]["state"] == "failed"
    metadata = task["metadata"]["knowledge_agent"]
    assert metadata["error"] == "model_limit"
    assert metadata["limits_hit"] == ["model_requests"]


async def test_saturated_capacity_is_rejected() -> None:
    settings = _settings(
        WORKFLOW_TASK_DEADLINE_SECONDS="1",
        WORKFLOW_UPSTREAM_TIMEOUT_SECONDS="1",
    )
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    fake = FakeSearchClient([])
    model = _model(_tool("routes"), _answer())
    executor = KnowledgeSearchExecutor(
        settings, fake, model=model, semaphore=semaphore
    )
    queue = EventQueue()
    context = RequestContext(
        request=MessageSendParams(message=_message("How do routes work?"))
    )

    await executor.execute(context, queue)

    events = await _drain(queue)
    assert _final_state(events) is TaskState.rejected
    assert fake.calls == []


async def test_deadline_fails_when_model_hangs() -> None:
    settings = _settings(
        WORKFLOW_TASK_DEADLINE_SECONDS="1",
        WORKFLOW_UPSTREAM_TIMEOUT_SECONDS="1",
    )
    fake = FakeSearchClient([])
    executor = KnowledgeSearchExecutor(
        settings, fake, model=_model(_sleeps(5))
    )
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
    artifact_events = [
        event for event in events if isinstance(event, TaskArtifactUpdateEvent)
    ]
    assert artifact_events == []


async def test_empty_message_completes_without_model_call() -> None:
    fake = FakeSearchClient([])
    model = _model(_answer())

    async with _client(_settings(), fake, model) as client:
        body = (await client.post("/a2a", json=_payload("   "))).json()

    task = body["result"]
    assert task["status"]["state"] == "completed"
    assert "concrete question" in _artifact_text(task)
