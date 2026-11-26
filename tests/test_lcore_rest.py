from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from knowledge_agent.config import Settings
from knowledge_agent.lcore_client import LcoreError, LcoreErrorKind
from knowledge_agent.lcore_rest import RestLcoreClient


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env(
        {
            "LCORE_RETRIEVER": "rest",
            "LCORE_REST_URL": "http://lcore.test:8080",
            "WORKFLOW_UPSTREAM_TIMEOUT_SECONDS": "30",
            "WORKFLOW_TASK_DEADLINE_SECONDS": "60",
        }
    )


def _document(
    *,
    document_id: str | None = "doc-1",
    title: str | None = "Route concepts",
    url: str | None = "https://docs.example/routes",
    source: str | None = "okp",
) -> dict[str, Any]:
    return {
        "doc_url": url,
        "doc_title": title,
        "source": source,
        "document_id": document_id,
    }


def _body(
    *,
    response: str = "An OpenShift route exposes a service.",
    documents: list[dict[str, Any]] | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    return {
        "conversation_id": "conv-1",
        "response": response,
        "rag_chunks": [{"content": "ignored chunk"}],
        "referenced_documents": [] if documents is None else documents,
        "tool_calls": [{"name": "file_search"}],
        "tool_results": [{"id": "ignored"}],
        "truncated": truncated,
    }


class FakeRest:
    def __init__(
        self,
        *,
        body: dict[str, Any] | None = None,
        response: httpx.Response | None = None,
        handler: Any = None,
    ) -> None:
        self.body = _body() if body is None else body
        self.response = response
        self.handler_override = handler
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.handler_override is not None:
            return self.handler_override(request)
        if self.response is not None:
            return self.response
        return httpx.Response(200, json=self.body)


async def _search(
    settings: Settings,
    fake: FakeRest,
    query: str = "how do OpenShift routes work?",
):
    transport = httpx.MockTransport(fake.handler)
    async with httpx.AsyncClient(
        transport=transport, timeout=httpx.Timeout(5)
    ) as http:
        client = RestLcoreClient(settings, httpx_client=http)
        return await client.search(query)


async def test_search_posts_the_query_only(settings: Settings) -> None:
    fake = FakeRest()

    result = await _search(settings, fake)

    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request.method == "POST"
    assert str(request.url) == "http://lcore.test:8080/v1/query"
    assert json.loads(request.content) == {
        "query": "how do OpenShift routes work?"
    }
    assert "authorization" not in request.headers
    assert "cookie" not in request.headers
    assert result.text == "An OpenShift route exposes a service."
    assert result.task_id is None
    assert result.context_id is None


async def test_referenced_documents_become_retrieved_evidence(
    settings: Settings,
) -> None:
    fake = FakeRest(body=_body(documents=[_document()]))

    result = await _search(settings, fake)

    assert result.evidence_status == "available"
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.kind == "document"
    assert evidence.source == "okp"
    assert evidence.document_id == "doc-1"
    assert evidence.title == "Route concepts"
    assert evidence.url == "https://docs.example/routes"
    assert evidence.support == "retrieved"


async def test_documents_are_deduplicated(settings: Settings) -> None:
    fake = FakeRest(
        body=_body(
            documents=[
                _document(),
                _document(title="Route concepts again"),
                _document(document_id="doc-2", url=None, title="Route limits"),
            ]
        )
    )

    result = await _search(settings, fake)

    assert [item.document_id for item in result.evidence] == [
        "doc-1",
        "doc-2",
    ]


async def test_documents_without_identifiers_are_skipped(
    settings: Settings,
) -> None:
    fake = FakeRest(
        body=_body(
            documents=[
                _document(document_id=None, title=None, url=None),
                _document(),
            ]
        )
    )

    result = await _search(settings, fake)

    assert len(result.evidence) == 1
    assert result.evidence[0].document_id == "doc-1"
    assert result.evidence_status == "available"


async def test_only_untraceable_documents_report_none(
    settings: Settings,
) -> None:
    fake = FakeRest(
        body=_body(documents=[_document(document_id=None, title=None, url=None)])
    )

    result = await _search(settings, fake)

    assert result.evidence == ()
    assert result.evidence_status == "none"


async def test_empty_documents_report_none(settings: Settings) -> None:
    fake = FakeRest(body=_body(documents=[]))

    result = await _search(settings, fake)

    assert result.evidence == ()
    assert result.evidence_status == "none"


async def test_missing_documents_report_none(settings: Settings) -> None:
    body = _body()
    del body["referenced_documents"]
    fake = FakeRest(body=body)

    result = await _search(settings, fake)

    assert result.evidence == ()
    assert result.evidence_status == "none"


async def test_null_documents_report_none(settings: Settings) -> None:
    body = _body()
    body["referenced_documents"] = None
    fake = FakeRest(body=body)

    result = await _search(settings, fake)

    assert result.evidence == ()
    assert result.evidence_status == "none"


async def test_local_truncation_is_marked() -> None:
    settings = Settings.from_env(
        {
            "LCORE_RETRIEVER": "rest",
            "LCORE_REST_URL": "http://lcore.test:8080",
            "WORKFLOW_MAX_MATERIAL_CHARS": "10",
        }
    )
    fake = FakeRest(body=_body(response="x" * 40))

    result = await _search(settings, fake)

    assert result.text == "x" * 10
    assert result.truncated is True


async def test_upstream_truncation_is_propagated(settings: Settings) -> None:
    fake = FakeRest(body=_body(response="short answer", truncated=True))

    result = await _search(settings, fake)

    assert result.text == "short answer"
    assert result.truncated is True


async def test_http_error_is_normalized(settings: Settings) -> None:
    fake = FakeRest(response=httpx.Response(503))

    with pytest.raises(LcoreError) as excinfo:
        await _search(settings, fake)

    assert excinfo.value.kind is LcoreErrorKind.HTTP_ERROR
    assert excinfo.value.status_code == 503


async def test_connection_error_is_an_http_error(settings: Settings) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    fake = FakeRest(handler=fail)

    with pytest.raises(LcoreError) as excinfo:
        await _search(settings, fake)

    assert excinfo.value.kind is LcoreErrorKind.HTTP_ERROR
    assert excinfo.value.status_code is None


async def test_timeout_is_normalized(settings: Settings) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    fake = FakeRest(handler=slow)

    with pytest.raises(LcoreError) as excinfo:
        await _search(settings, fake)

    assert excinfo.value.kind is LcoreErrorKind.TIMEOUT


async def test_non_json_response_is_invalid(settings: Settings) -> None:
    fake = FakeRest(response=httpx.Response(200, text="not json"))

    with pytest.raises(LcoreError) as excinfo:
        await _search(settings, fake)

    assert excinfo.value.kind is LcoreErrorKind.INVALID_RESPONSE


async def test_missing_answer_is_invalid(settings: Settings) -> None:
    fake = FakeRest(body={"referenced_documents": [_document()]})

    with pytest.raises(LcoreError) as excinfo:
        await _search(settings, fake)

    assert excinfo.value.kind is LcoreErrorKind.INVALID_RESPONSE


async def test_empty_answer_is_invalid(settings: Settings) -> None:
    fake = FakeRest(body=_body(response="   "))

    with pytest.raises(LcoreError) as excinfo:
        await _search(settings, fake)

    assert excinfo.value.kind is LcoreErrorKind.INVALID_RESPONSE


async def test_empty_query_is_rejected(settings: Settings) -> None:
    fake = FakeRest()
    transport = httpx.MockTransport(fake.handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = RestLcoreClient(settings, httpx_client=http)
        with pytest.raises(ValueError):
            await client.search("   ")
    assert fake.requests == []


async def test_aclose_closes_the_owned_client(settings: Settings) -> None:
    client = RestLcoreClient(settings)

    await client.aclose()

    assert client._http.is_closed is True
