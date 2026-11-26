"""State and contracts for the agent-owned reasoning loop.

See `docs/workflow-loop.md` for the loop shape and its component mapping.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from knowledge_agent.lcore_client import LcoreError, LcoreEvidence, LcoreResult

logger = logging.getLogger(__name__)

WORKFLOW_METADATA_KEY = "knowledge_agent"
CLARIFICATION_PHASE = "awaiting_clarification"
EMPTY_REQUEST_MESSAGE = "I need a concrete question to search for."

EvidenceStatus = Literal["available", "none", "unavailable", "not_configured"]
SupportKind = Literal["retrieved", "cited"]
ReferenceKey = tuple[str | None, ...]


class SearchClient(Protocol):
    """Minimal upstream surface the loop depends on."""

    async def search(self, query: str) -> LcoreResult: ...


class SearchReference(BaseModel):
    """Structured reference exposed to the model without upstream identifiers."""

    source: str | None = None
    document_id: str | None = None
    title: str | None = None
    url: str | None = None
    support: SupportKind | None = None


class SearchObservation(BaseModel):
    """Bounded result of one LCORE search, returned to the agent model."""

    query: str
    text: str
    evidence_status: EvidenceStatus
    references: list[SearchReference] = Field(default_factory=list)
    search_index: int
    truncated: bool = False
    limit_reached: bool = False


@dataclass
class SearchState:
    """Mutable per-task loop state shared with the agent tools."""

    client: SearchClient
    max_searches: int
    searches: int = 0
    results: list[LcoreResult] = field(default_factory=list)
    failure: LcoreError | None = None
    clarification_used: bool = False

    @property
    def search_limit_reached(self) -> bool:
        """Whether another search would exceed the configured cap."""
        return self.searches >= self.max_searches


def reference_key(reference: SearchReference) -> ReferenceKey:
    """Stable identity used to union references across searches."""
    if reference.source or reference.document_id:
        return ("document", reference.source, reference.document_id)
    return ("document", None, None, reference.url, reference.title)


def to_reference(evidence: LcoreEvidence) -> SearchReference:
    """Project one upstream evidence item onto the model-facing contract."""
    return SearchReference(
        source=evidence.source,
        document_id=evidence.document_id,
        title=evidence.title,
        url=evidence.url,
        support=evidence.support,
    )


async def search_knowledge(
    state: SearchState, query: str
) -> SearchObservation:
    """Run one bounded LCORE search and normalize the observation."""
    index = state.searches + 1
    if state.search_limit_reached:
        return SearchObservation(
            query=query,
            text="",
            evidence_status="unavailable",
            search_index=index,
            limit_reached=True,
        )

    state.searches = index
    try:
        result = await state.client.search(query)
    except LcoreError as exc:
        state.failure = exc
        logger.warning(
            "LCORE search failed: kind=%s status=%s rpc_code=%s task_state=%s",
            exc.kind,
            exc.status_code,
            exc.rpc_code,
            exc.task_state,
        )
        return SearchObservation(
            query=query,
            text="",
            evidence_status="unavailable",
            search_index=index,
            limit_reached=True,
        )

    state.results.append(result)
    return SearchObservation(
        query=query,
        text=result.text,
        evidence_status=result.evidence_status,
        references=[to_reference(item) for item in result.evidence],
        search_index=index,
        truncated=result.truncated,
        limit_reached=state.search_limit_reached,
    )


def retrieved_evidence(
    state: SearchState,
) -> list[tuple[int, SearchReference]]:
    """Union retrieved references across searches with their search index."""
    unique: dict[ReferenceKey, tuple[int, SearchReference]] = {}
    for index, result in enumerate(state.results, start=1):
        for item in result.evidence:
            if item.support != "retrieved":
                continue
            reference = to_reference(item)
            unique.setdefault(reference_key(reference), (index, reference))
    return list(unique.values())


def combined_evidence_status(state: SearchState) -> EvidenceStatus:
    """Aggregate per-search evidence states into one task-level status."""
    statuses = [result.evidence_status for result in state.results]
    if "available" in statuses:
        return "available"
    if "not_configured" in statuses:
        return "not_configured"
    if "none" in statuses:
        return "none"
    return "unavailable"


def compose_prompt(question: str, clarification: str | None) -> str:
    """Combine the original request with the caller's clarification."""
    base = question.strip()
    extra = (clarification or "").strip()
    if not extra:
        return base
    return (
        f"{base}\n\n"
        f"The caller answered the clarification request with: {extra}"
    )


def clarification_metadata(question: str) -> dict[str, object]:
    """Task metadata that lets the next request resume this conversation."""
    return {
        WORKFLOW_METADATA_KEY: {
            "phase": CLARIFICATION_PHASE,
            "question": question,
        }
    }


def read_clarification_question(
    task_metadata: Mapping[str, object] | None,
) -> str | None:
    """Return the stored question when the task is awaiting clarification."""
    if not task_metadata:
        return None
    state = task_metadata.get(WORKFLOW_METADATA_KEY)
    if not isinstance(state, Mapping):
        return None
    if state.get("phase") != CLARIFICATION_PHASE:
        return None
    question = state.get("question")
    if not isinstance(question, str) or not question.strip():
        return None
    return question
