"""REST transport for LCORE retrieval with provenance documents.

LCORE's ``POST /v1/query`` returns ``referenced_documents``, which the A2A
path does not. The transport is selected once at startup and never merged with
the A2A client. Requests are query-only: no credentials, conversation IDs, or
model, provider, vector-store, and source-selection fields.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from knowledge_agent.config import Settings
from knowledge_agent.lcore_client import (
    EvidenceKey,
    LcoreError,
    LcoreErrorKind,
    LcoreEvidence,
    LcoreResult,
    evidence_key,
)

logger = logging.getLogger(__name__)

QUERY_PATH = "/v1/query"
EMPTY_ANSWER_MESSAGE = "LCORE returned an empty answer"


class _ReferencedDocument(BaseModel):
    """One document reference from the LCORE query response."""

    model_config = ConfigDict(extra="ignore")

    doc_url: str | None = None
    doc_title: str | None = None
    source: str | None = None
    document_id: str | None = None


class _QueryResponse(BaseModel):
    """Bounded view of the LCORE query response."""

    model_config = ConfigDict(extra="ignore")

    response: str
    referenced_documents: list[_ReferencedDocument] | None = None
    truncated: bool = False


class RestLcoreClient:
    """Query LCORE's REST endpoint for answer text and referenced documents."""

    def __init__(
        self,
        settings: Settings,
        *,
        httpx_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_http_client = httpx_client is None
        self._http = httpx_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.workflow.upstream_timeout_seconds)
        )

    async def search(self, query: str) -> LcoreResult:
        """Send one query to LCORE and normalize its referenced documents."""
        text = query.strip()
        if not text:
            raise ValueError("query must not be empty")

        url = f"{self._settings.lcore_rest_url}{QUERY_PATH}"
        try:
            response = await self._http.post(url, json={"query": text})
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LcoreError(
                LcoreErrorKind.TIMEOUT, "LCORE request timed out"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LcoreError(
                LcoreErrorKind.HTTP_ERROR,
                f"LCORE HTTP error {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise LcoreError(
                LcoreErrorKind.HTTP_ERROR, "LCORE request failed"
            ) from exc

        body = _parse_body(response)
        answer = body.response.strip()
        if not answer:
            raise LcoreError(
                LcoreErrorKind.INVALID_RESPONSE, EMPTY_ANSWER_MESSAGE
            )

        evidence = _documents_to_evidence(body.referenced_documents or ())
        status = "available" if evidence else "none"
        truncated = body.truncated
        limit = self._settings.workflow.max_material_chars
        if len(answer) > limit:
            answer = answer[:limit].rstrip()
            truncated = True
        logger.info(
            "LCORE REST retrieval: url=%s documents=%d evidence_status=%s "
            "truncated=%s",
            url,
            len(evidence),
            status,
            truncated,
        )
        return LcoreResult(
            text=answer,
            task_id=None,
            context_id=None,
            evidence=evidence,
            evidence_status=status,
            truncated=truncated,
        )

    async def aclose(self) -> None:
        """Close the HTTP client when this instance created it."""
        if self._owns_http_client:
            await self._http.aclose()


def _parse_body(response: httpx.Response) -> _QueryResponse:
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LcoreError(
            LcoreErrorKind.INVALID_RESPONSE,
            "LCORE returned an invalid JSON response",
        ) from exc
    try:
        return _QueryResponse.model_validate(payload)
    except ValidationError as exc:
        raise LcoreError(
            LcoreErrorKind.INVALID_RESPONSE,
            "LCORE returned an invalid query response",
        ) from exc


def _documents_to_evidence(
    documents: Sequence[_ReferencedDocument] | Iterable[_ReferencedDocument],
) -> tuple[LcoreEvidence, ...]:
    items: list[LcoreEvidence] = []
    seen: set[EvidenceKey] = set()
    for document in documents:
        evidence = LcoreEvidence(
            kind="document",
            source=_clean(document.source),
            document_id=_clean(document.document_id),
            url=_clean(document.doc_url),
            title=_clean(document.doc_title),
            support="retrieved",
        )
        if not any((evidence.document_id, evidence.url, evidence.title)):
            continue
        key = evidence_key(evidence)
        if key in seen:
            continue
        seen.add(key)
        items.append(evidence)
    return tuple(items)


def _clean(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
