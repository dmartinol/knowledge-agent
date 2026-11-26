from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from knowledge_agent.config import Settings
from knowledge_agent.lcore_client import (
    LcoreClient,
    LcoreError,
    LcoreErrorKind,
)


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env(
        {
            "LCORE_AGENT_CARD_URL": (
                "http://lcore.test/.well-known/agent-card.json"
            ),
            "WORKFLOW_UPSTREAM_TIMEOUT_SECONDS": "30",
            "WORKFLOW_TASK_DEADLINE_SECONDS": "60",
        }
    )


def _card_payload(
    *,
    protocol_version: str = "0.3.0",
    preferred_transport: str = "JSONRPC",
) -> dict[str, Any]:
    return {
        "name": "Test LCORE",
        "description": "Test knowledge service",
        "url": "http://lcore.test/a2a",
        "version": "0.1.0",
        "protocolVersion": protocol_version,
        "preferredTransport": preferred_transport,
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "security": [],
        "securitySchemes": {},
        "skills": [
            {
                "id": "knowledge",
                "name": "Knowledge",
                "description": "Answers questions",
                "tags": ["test"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            }
        ],
    }


def _task_result(
    *,
    state: str = "completed",
    text: str = "answer",
    artifacts: list[dict[str, Any]] | None = None,
    context_id: str = "ctx-1",
) -> dict[str, Any]:
    if artifacts is None:
        artifacts = [
            {
                "artifactId": "artifact-1",
                "parts": [{"kind": "text", "text": text}],
            }
        ]
    return {
        "id": "task-1",
        "contextId": context_id,
        "kind": "task",
        "status": {"state": state},
        "artifacts": artifacts,
    }


def _rpc_result(result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": "ignored", "result": result}


class FakeLcore:
    def __init__(
        self,
        *,
        card: dict[str, Any] | httpx.Response | None = None,
        rpc: dict[str, Any] | httpx.Response | None = None,
    ) -> None:
        self.card = card if card is not None else _card_payload()
        self.rpc = rpc if rpc is not None else _rpc_result(_task_result())
        self.card_requests = 0
        self.rpc_requests: list[dict[str, Any]] = []
        self.card_handler: Callable[[httpx.Request], httpx.Response] | None = (
            None
        )
        self.rpc_handler: Callable[[httpx.Request], httpx.Response] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/agent-card.json":
            self.card_requests += 1
            if self.card_handler is not None:
                return self.card_handler(request)
            if isinstance(self.card, httpx.Response):
                return self.card
            return httpx.Response(200, json=self.card)
        if request.url.path == "/a2a":
            self.rpc_requests.append(json.loads(request.content))
            if self.rpc_handler is not None:
                return self.rpc_handler(request)
            if isinstance(self.rpc, httpx.Response):
                return self.rpc
            return httpx.Response(200, json=self.rpc)
        return httpx.Response(404)


async def _search(
    settings: Settings,
    fake: FakeLcore,
    query: str = "what is a pod?",
    *,
    context_id: str | None = None,
):
    transport = httpx.MockTransport(fake.handler)
    async with httpx.AsyncClient(
        transport=transport, timeout=httpx.Timeout(5)
    ) as http:
        client = LcoreClient(settings, httpx_client=http)
        return await client.search(query, context_id=context_id)


async def test_search_discovers_card_and_sends_no_metadata(
    settings: Settings,
) -> None:
    fake = FakeLcore()

    result = await _search(settings, fake)

    assert result.text == "answer"
    assert result.task_id == "task-1"
    assert result.context_id == "ctx-1"
    assert fake.card_requests == 1
    body = fake.rpc_requests[0]
    assert body["method"] == "message/send"
    params = body["params"]
    assert "metadata" not in params
    assert "metadata" not in params["message"]
    assert params["message"]["parts"][0]["text"] == "what is a pod?"
    assert params["configuration"]["blocking"] is True
    assert params["configuration"]["acceptedOutputModes"] == ["text/plain"]
    encoded = json.dumps(body)
    for banned in ("model", "provider", "vector_store_ids"):
        assert banned not in encoded


async def test_card_is_cached_and_context_id_is_forwarded(
    settings: Settings,
) -> None:
    fake = FakeLcore()
    transport = httpx.MockTransport(fake.handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = LcoreClient(settings, httpx_client=http)
        await client.search("first")
        await client.search("second", context_id="ctx-upstream")

    assert fake.card_requests == 1
    assert fake.rpc_requests[1]["params"]["message"]["contextId"] == (
        "ctx-upstream"
    )
    assert "metadata" not in fake.rpc_requests[1]["params"]


@pytest.mark.parametrize(
    ("card", "expected_kind"),
    [
        (_card_payload(protocol_version="0.2.0"), LcoreErrorKind.PROTOCOL_UNSUPPORTED),
        (_card_payload(preferred_transport="GRPC"), LcoreErrorKind.PROTOCOL_UNSUPPORTED),
    ],
)
async def test_incompatible_card_is_rejected_before_rpc(
    settings: Settings,
    card: dict[str, Any],
    expected_kind: LcoreErrorKind,
) -> None:
    fake = FakeLcore(card=card)

    with pytest.raises(LcoreError) as exc_info:
        await _search(settings, fake)

    assert exc_info.value.kind is expected_kind
    assert fake.rpc_requests == []


async def test_jsonrpc_error_is_normalized(settings: Settings) -> None:
    fake = FakeLcore(
        rpc={
            "jsonrpc": "2.0",
            "id": "ignored",
            "error": {"code": -32603, "message": "Model not found"},
        }
    )

    with pytest.raises(LcoreError) as exc_info:
        await _search(settings, fake)

    assert exc_info.value.kind is LcoreErrorKind.JSONRPC_ERROR
    assert exc_info.value.rpc_code == -32603


async def test_http_error_is_normalized(settings: Settings) -> None:
    fake = FakeLcore(rpc=httpx.Response(500, json={"detail": "boom"}))

    with pytest.raises(LcoreError) as exc_info:
        await _search(settings, fake)

    assert exc_info.value.kind is LcoreErrorKind.HTTP_ERROR
    assert exc_info.value.status_code == 500


async def test_timeout_is_normalized(settings: Settings) -> None:
    fake = FakeLcore()

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow upstream", request=request)

    fake.rpc_handler = timeout

    with pytest.raises(LcoreError) as exc_info:
        await _search(settings, fake)

    assert exc_info.value.kind is LcoreErrorKind.TIMEOUT


async def test_failed_task_is_normalized(settings: Settings) -> None:
    fake = FakeLcore(
        rpc=_rpc_result(_task_result(state="failed", artifacts=[]))
    )

    with pytest.raises(LcoreError) as exc_info:
        await _search(settings, fake)

    assert exc_info.value.kind is LcoreErrorKind.TASK_NOT_COMPLETED
    assert exc_info.value.task_state == "failed"


async def test_completed_task_without_text_is_invalid(
    settings: Settings,
) -> None:
    fake = FakeLcore(
        rpc=_rpc_result(
            _task_result(
                artifacts=[
                    {
                        "artifactId": "artifact-1",
                        "parts": [{"kind": "text", "text": "   "}],
                    }
                ]
            )
        )
    )

    with pytest.raises(LcoreError) as exc_info:
        await _search(settings, fake)

    assert exc_info.value.kind is LcoreErrorKind.INVALID_RESPONSE


async def test_direct_message_response_is_normalized(settings: Settings) -> None:
    fake = FakeLcore(
        rpc=_rpc_result(
            {
                "kind": "message",
                "role": "agent",
                "messageId": "message-1",
                "contextId": "ctx-message",
                "parts": [{"kind": "text", "text": "direct answer"}],
            }
        )
    )

    result = await _search(settings, fake)

    assert result.text == "direct answer"
    assert result.task_id is None
    assert result.context_id == "ctx-message"
    assert result.evidence_status == "unavailable"


async def test_evidence_is_normalized_and_deduplicated(
    settings: Settings,
) -> None:
    chunk = {
        "content": "chunk text",
        "score": 0.42,
        "source": "okp",
        "attributes": {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "source": "okp",
            "title": "Document One",
        },
    }
    artifacts = [
        {
            "artifactId": "artifact-1",
            "parts": [{"kind": "text", "text": "answer"}],
            "metadata": {
                "referenced_documents": [
                    {
                        "doc_url": "https://docs.example/one",
                        "doc_title": "Document One",
                        "source": "okp",
                        "document_id": "doc-1",
                    }
                ],
                "rag_chunks": [chunk, chunk],
            },
        }
    ]
    fake = FakeLcore(rpc=_rpc_result(_task_result(artifacts=artifacts)))

    result = await _search(settings, fake)

    assert result.evidence_status == "available"
    assert len(result.evidence) == 2
    document = result.evidence[0]
    assert document.kind == "document"
    assert document.document_id == "doc-1"
    assert document.url == "https://docs.example/one"
    chunk_evidence = result.evidence[1]
    assert chunk_evidence.kind == "chunk"
    assert chunk_evidence.chunk_id == "chunk-1"
    assert chunk_evidence.score == pytest.approx(0.42)


async def test_empty_evidence_payload_is_none(settings: Settings) -> None:
    artifacts = [
        {
            "artifactId": "artifact-1",
            "parts": [{"kind": "text", "text": "answer"}],
            "metadata": {"referenced_documents": []},
        }
    ]
    fake = FakeLcore(rpc=_rpc_result(_task_result(artifacts=artifacts)))

    result = await _search(settings, fake)

    assert result.evidence == ()
    assert result.evidence_status == "none"


async def test_malformed_evidence_payload_is_unavailable(
    settings: Settings,
) -> None:
    artifacts = [
        {
            "artifactId": "artifact-1",
            "parts": [{"kind": "text", "text": "answer"}],
            "metadata": {"referenced_documents": [{"unexpected": "value"}]},
        }
    ]
    fake = FakeLcore(rpc=_rpc_result(_task_result(artifacts=artifacts)))

    result = await _search(settings, fake)

    assert result.evidence == ()
    assert result.evidence_status == "unavailable"


async def test_missing_evidence_and_inline_markers_are_preserved(
    settings: Settings,
) -> None:
    marker_text = "Answer <|/documentation/example|>"
    fake = FakeLcore(rpc=_rpc_result(_task_result(text=marker_text)))

    result = await _search(settings, fake)

    assert result.text == marker_text
    assert result.evidence == ()
    assert result.evidence_status == "unavailable"


async def test_card_http_error_is_card_unavailable(
    settings: Settings,
) -> None:
    fake = FakeLcore(card=httpx.Response(503, json={"detail": "down"}))

    with pytest.raises(LcoreError) as exc_info:
        await _search(settings, fake)

    assert exc_info.value.kind is LcoreErrorKind.CARD_UNAVAILABLE
    assert exc_info.value.status_code == 503


async def test_malformed_card_is_invalid_response(
    settings: Settings,
) -> None:
    fake = FakeLcore(card=httpx.Response(200, text="not json"))

    with pytest.raises(LcoreError) as exc_info:
        await _search(settings, fake)

    assert exc_info.value.kind is LcoreErrorKind.INVALID_RESPONSE
