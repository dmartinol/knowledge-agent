"""A2A client for the Lightspeed Core Stack knowledge service."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import httpx
from a2a.client import (
    A2AClientError,
    A2AClientHTTPError,
    A2AClientJSONError,
    A2AClientTimeoutError,
    Client,
    ClientConfig,
    ClientEvent,
    ClientFactory,
)
from a2a.client.errors import A2AClientJSONRPCError
from a2a.types import (
    AgentCard,
    Artifact,
    DataPart,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TextPart,
    TransportProtocol,
)
from pydantic import ValidationError

from knowledge_agent.config import Settings

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_PREFIX = "0.3."
EVIDENCE_ENVELOPE_KEY = "evidence"
EVIDENCE_DOCUMENT_KEYS = ("referenced_documents",)
EVIDENCE_CHUNK_KEYS = ("rag_chunks",)
LOOPBACK_HOSTS: frozenset[str] = frozenset(
    {"localhost", "0.0.0.0", "127.0.0.1", "::1"}
)

EvidenceKind = Literal["document", "chunk"]
SupportKind = Literal["retrieved", "cited"]
EvidenceStatus = Literal["unavailable", "none", "available", "not_configured"]
EvidenceKey = tuple[str, str | None, str | None, str | None, str | None]
ENVELOPE_STATUSES: frozenset[str] = frozenset(
    {"available", "none", "unavailable", "not_configured"}
)


def evidence_key(evidence: LcoreEvidence) -> EvidenceKey:
    """Identity used to deduplicate one evidence item across normalizations."""
    if evidence.kind == "document":
        if evidence.source or evidence.document_id:
            return ("document", evidence.source, evidence.document_id, None, None)
        return ("document", None, None, evidence.url, evidence.title)
    return (
        evidence.kind,
        evidence.url,
        evidence.document_id,
        evidence.chunk_id,
        evidence.excerpt,
    )


class LcoreErrorKind(StrEnum):
    """Stable failure categories for workflow decisions and logs."""

    CARD_UNAVAILABLE = "card_unavailable"
    PROTOCOL_UNSUPPORTED = "protocol_unsupported"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"
    JSONRPC_ERROR = "jsonrpc_error"
    TASK_NOT_COMPLETED = "task_not_completed"
    INVALID_RESPONSE = "invalid_response"


class LcoreError(Exception):
    """Normalized upstream failure without exposing request content."""

    def __init__(
        self,
        kind: LcoreErrorKind,
        message: str,
        *,
        status_code: int | None = None,
        rpc_code: int | None = None,
        task_state: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status_code = status_code
        self.rpc_code = rpc_code
        self.task_state = task_state


@dataclass(frozen=True)
class LcoreEvidence:
    """One traceable document or chunk supplied by LCORE."""

    kind: EvidenceKind
    source: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    url: str | None = None
    title: str | None = None
    excerpt: str | None = None
    score: float | None = None
    support: SupportKind | None = None


@dataclass(frozen=True)
class LcoreResult:
    """Normalized answer and evidence state returned by LCORE."""

    text: str
    task_id: str | None
    context_id: str | None
    evidence: tuple[LcoreEvidence, ...] = ()
    evidence_status: EvidenceStatus = "unavailable"
    truncated: bool = False


class LcoreClient:
    """Discover LCORE and send bounded, metadata-free A2A queries."""

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
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def search(self, query: str) -> LcoreResult:
        """Send one question to LCORE in a fresh conversation."""
        text = query.strip()
        if not text:
            raise ValueError("query must not be empty")

        client = await self._get_client()
        message = Message(
            role=Role.user,
            parts=[Part(root=TextPart(text=text))],
            message_id=str(uuid4()),
        )

        last_event: ClientEvent | Message | None = None
        try:
            async for event in client.send_message(message):
                last_event = event
        except A2AClientTimeoutError as exc:
            raise LcoreError(
                LcoreErrorKind.TIMEOUT, "LCORE request timed out"
            ) from exc
        except A2AClientJSONRPCError as exc:
            raise LcoreError(
                LcoreErrorKind.JSONRPC_ERROR,
                f"LCORE JSON-RPC error {exc.error.code}: {exc.error.message}",
                rpc_code=exc.error.code,
            ) from exc
        except A2AClientHTTPError as exc:
            raise LcoreError(
                LcoreErrorKind.HTTP_ERROR,
                f"LCORE HTTP error {exc.status_code}",
                status_code=exc.status_code,
            ) from exc
        except A2AClientJSONError as exc:
            raise LcoreError(
                LcoreErrorKind.INVALID_RESPONSE,
                "LCORE returned an invalid JSON response",
            ) from exc
        except A2AClientError as exc:
            raise LcoreError(
                LcoreErrorKind.INVALID_RESPONSE,
                "LCORE client request failed",
            ) from exc

        if last_event is None:
            raise LcoreError(
                LcoreErrorKind.INVALID_RESPONSE, "LCORE returned no response"
            )
        if isinstance(last_event, Message):
            result = _result_from_message(last_event)
        else:
            result = _result_from_task(last_event[0])
        limit = self._settings.workflow.max_material_chars
        if len(result.text) <= limit:
            return result
        return replace(result, text=result.text[:limit].rstrip(), truncated=True)

    async def aclose(self) -> None:
        """Close the HTTP client when this instance created it."""
        if self._owns_http_client:
            await self._http.aclose()

    async def _get_client(self) -> Client:
        async with self._lock:
            if self._client is not None:
                return self._client
            card = await self._discover_card()
            try:
                self._client = ClientFactory(self._client_config()).create(card)
            except ValueError as exc:
                raise LcoreError(
                    LcoreErrorKind.PROTOCOL_UNSUPPORTED,
                    "LCORE Agent Card does not expose a usable JSON-RPC client",
                ) from exc
            return self._client

    def _client_config(self) -> ClientConfig:
        return ClientConfig(
            streaming=False,
            polling=False,
            httpx_client=self._http,
            supported_transports=[TransportProtocol.jsonrpc],
            accepted_output_modes=["text/plain"],
        )

    async def _discover_card(self) -> AgentCard:
        url = self._settings.lcore_agent_card_url
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            card = AgentCard.model_validate(response.json())
        except httpx.TimeoutException as exc:
            raise LcoreError(
                LcoreErrorKind.TIMEOUT, "LCORE Agent Card request timed out"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LcoreError(
                LcoreErrorKind.CARD_UNAVAILABLE,
                f"LCORE Agent Card returned HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise LcoreError(
                LcoreErrorKind.CARD_UNAVAILABLE,
                "LCORE Agent Card could not be reached",
            ) from exc
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LcoreError(
                LcoreErrorKind.INVALID_RESPONSE,
                "LCORE Agent Card is not a valid Agent Card",
            ) from exc

        self._validate_card(card)
        card = self._reachable_card(card)
        logger.info(
            "Discovered LCORE Agent Card: name=%s version=%s url=%s "
            "protocol=%s transport=%s",
            card.name,
            card.version,
            card.url,
            card.protocol_version,
            card.preferred_transport,
        )
        return card

    def _validate_card(self, card: AgentCard) -> None:
        version = card.protocol_version or ""
        if not version.startswith(SUPPORTED_PROTOCOL_PREFIX):
            raise LcoreError(
                LcoreErrorKind.PROTOCOL_UNSUPPORTED,
                f"unsupported LCORE protocol version {version!r}",
            )
        if not _advertises_jsonrpc(card):
            raise LcoreError(
                LcoreErrorKind.PROTOCOL_UNSUPPORTED,
                "LCORE Agent Card does not advertise JSON-RPC",
            )
        parsed_url = urlparse(card.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise LcoreError(
                LcoreErrorKind.INVALID_RESPONSE,
                "LCORE Agent Card has an invalid JSON-RPC URL",
            )

    def _reachable_card(self, card: AgentCard) -> AgentCard:
        """Point loopback card endpoints at the configured card host.

        A2A servers commonly publish their bind address (``localhost`` or
        ``0.0.0.0``) in the Agent Card. That address is not reachable from
        another pod, so the scheme, host, and port of the configured card URL
        are substituted while every advertised path is preserved.
        """
        card_url = self._settings.lcore_agent_card_url
        url = _peer_endpoint(card.url, card_url)
        interfaces = [
            replace(interface, url=_peer_endpoint(interface.url, card_url))
            if interface.url
            else interface
            for interface in card.additional_interfaces or []
        ]
        if url == card.url and interfaces == list(card.additional_interfaces or []):
            return card
        logger.info(
            "Rewrote loopback LCORE endpoint url=%s to url=%s", card.url, url
        )
        return card.model_copy(
            update={"url": url, "additional_interfaces": interfaces}
        )


def _peer_endpoint(advertised: str, card_url: str) -> str:
    """Return an advertised endpoint reached through the configured host.

    Only loopback and unspecified addresses are rewritten, because they are
    unreachable from another pod. Anything else is returned untouched.
    """
    advertised_parts = urlparse(advertised)
    if advertised_parts.hostname not in LOOPBACK_HOSTS:
        return advertised
    config_parts = urlparse(card_url)
    if not config_parts.netloc:
        return advertised
    return urlunparse(
        advertised_parts._replace(
            scheme=config_parts.scheme or advertised_parts.scheme,
            netloc=config_parts.netloc,
        )
    )


def _advertises_jsonrpc(card: AgentCard) -> bool:
    if (card.preferred_transport or "").upper() == "JSONRPC":
        return True
    return any(
        (interface.transport or "").upper() == "JSONRPC"
        for interface in card.additional_interfaces or []
    )


def _result_from_task(task: Task) -> LcoreResult:
    if task.status.state is not TaskState.completed:
        state = task.status.state.value
        raise LcoreError(
            LcoreErrorKind.TASK_NOT_COMPLETED,
            f"LCORE task ended in state {state}",
            task_state=state,
        )
    artifacts = task.artifacts or []
    text = _join_text_parts(
        part for artifact in artifacts for part in artifact.parts
    )
    if not text:
        raise LcoreError(
            LcoreErrorKind.INVALID_RESPONSE,
            "LCORE completed without answer text",
        )
    evidence, status = _extract_evidence(artifacts=artifacts)
    return LcoreResult(
        text=text,
        task_id=task.id,
        context_id=task.context_id,
        evidence=evidence,
        evidence_status=status,
    )


def _result_from_message(message: Message) -> LcoreResult:
    text = _join_text_parts(message.parts)
    if not text:
        raise LcoreError(
            LcoreErrorKind.INVALID_RESPONSE,
            "LCORE returned an empty message",
        )
    evidence, status = _extract_evidence(parts=message.parts)
    return LcoreResult(
        text=text,
        task_id=None,
        context_id=message.context_id,
        evidence=evidence,
        evidence_status=status,
    )


def _join_text_parts(parts: Iterable[Part]) -> str:
    texts = [
        part.root.text.strip()
        for part in parts
        if isinstance(part.root, TextPart) and part.root.text.strip()
    ]
    return "\n\n".join(texts).strip()


def _extract_evidence(
    *,
    artifacts: Sequence[Artifact] = (),
    parts: Sequence[Part] = (),
) -> tuple[tuple[LcoreEvidence, ...], EvidenceStatus]:
    containers: list[Mapping[str, Any]] = []
    for artifact in artifacts:
        if artifact.metadata:
            containers.append(artifact.metadata)
        containers.extend(_part_containers(artifact.parts))
    containers.extend(_part_containers(parts))

    envelope_status: str | None = None
    found_empty_payload = False
    found_nonempty_payload = False
    evidence: list[LcoreEvidence] = []
    seen: set[EvidenceKey] = set()
    for container in containers:
        envelope = _as_envelope(container)
        if envelope is not None:
            declared = _as_text(envelope.get("status"))
            if declared in ENVELOPE_STATUSES and envelope_status is None:
                envelope_status = declared
            documents = envelope.get("documents")
            if isinstance(documents, list):
                found_empty_payload = found_empty_payload or not documents
                found_nonempty_payload = (
                    found_nonempty_payload or bool(documents)
                )
                for item in documents:
                    parsed = _parse_document(item)
                    if parsed is not None:
                        _append_unique(parsed, evidence, seen)
        documents, has_documents = _evidence_items(
            container, EVIDENCE_DOCUMENT_KEYS
        )
        if has_documents:
            found_empty_payload = found_empty_payload or not documents
            found_nonempty_payload = found_nonempty_payload or bool(documents)
        for item in documents:
            parsed = _parse_document(item)
            if parsed is not None:
                _append_unique(parsed, evidence, seen)
        chunks, has_chunks = _evidence_items(container, EVIDENCE_CHUNK_KEYS)
        if has_chunks:
            found_empty_payload = found_empty_payload or not chunks
            found_nonempty_payload = found_nonempty_payload or bool(chunks)
        for item in chunks:
            parsed = _parse_chunk(item)
            if parsed is not None:
                _append_unique(parsed, evidence, seen)

    if evidence:
        return tuple(evidence), "available"
    if envelope_status == "none":
        return (), "none"
    if envelope_status == "not_configured":
        return (), "not_configured"
    if envelope_status == "unavailable":
        return (), "unavailable"
    if found_nonempty_payload:
        return (), "unavailable"
    if found_empty_payload:
        return (), "none"
    return (), "unavailable"


def _as_envelope(container: Mapping[str, Any]) -> Mapping[str, Any] | None:
    nested = container.get(EVIDENCE_ENVELOPE_KEY)
    if isinstance(nested, Mapping):
        return nested
    if "documents" in container and "status" in container:
        return container
    return None


def _part_containers(parts: Sequence[Part]) -> list[Mapping[str, Any]]:
    containers: list[Mapping[str, Any]] = []
    for part in parts:
        if part.root.metadata:
            containers.append(part.root.metadata)
        if isinstance(part.root, DataPart):
            containers.append(part.root.data)
    return containers


def _evidence_items(
    container: Mapping[str, Any], keys: Sequence[str]
) -> tuple[list[Any], bool]:
    items: list[Any] = []
    found = False
    for key in keys:
        value = container.get(key)
        if isinstance(value, list):
            found = True
            items.extend(value)
    return items, found


def _parse_document(item: Any) -> LcoreEvidence | None:
    if not isinstance(item, Mapping):
        return None
    evidence = LcoreEvidence(
        kind="document",
        source=_as_text(item.get("source")),
        document_id=_as_text(item.get("document_id")),
        url=_as_text(item.get("url")) or _as_text(item.get("doc_url")),
        title=_as_text(item.get("title")) or _as_text(item.get("doc_title")),
        support=_as_support(item.get("support")),
    )
    if not any((evidence.document_id, evidence.url, evidence.title)):
        return None
    return evidence


def _parse_chunk(item: Any) -> LcoreEvidence | None:
    if not isinstance(item, Mapping):
        return None
    attributes = item.get("attributes")
    attrs = attributes if isinstance(attributes, Mapping) else {}
    evidence = LcoreEvidence(
        kind="chunk",
        source=_as_text(item.get("source")) or _as_text(attrs.get("source")),
        document_id=_as_text(attrs.get("document_id")),
        chunk_id=_as_text(attrs.get("chunk_id")),
        url=_as_text(attrs.get("doc_url")),
        title=_as_text(attrs.get("title")),
        excerpt=_as_text(item.get("content")),
        score=_as_score(item.get("score")),
    )
    if not any(
        (evidence.document_id, evidence.chunk_id, evidence.url, evidence.excerpt)
    ):
        return None
    return evidence


def _append_unique(
    evidence: LcoreEvidence,
    items: list[LcoreEvidence],
    seen: set[EvidenceKey],
) -> None:
    key = evidence_key(evidence)
    if key in seen:
        return
    seen.add(key)
    items.append(evidence)


def _as_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _as_score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_support(value: Any) -> SupportKind | None:
    if value == "retrieved":
        return "retrieved"
    if value == "cited":
        return "cited"
    return None
