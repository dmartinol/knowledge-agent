"""Deterministic rendering of the answer, gaps, sources, and metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass

from knowledge_agent.loop import (
    SearchReference,
    SearchState,
    combined_evidence_status,
    retrieved_evidence,
)
from knowledge_agent.reasoning import KnowledgeAnswer

SEARCH_LIMIT_GAP = (
    "The search limit was reached, so the answer may not cover every relevant "
    "source."
)
UNVERIFIED_LIMITATION = (
    "Unverified: the knowledge service returned no traceable references for "
    "this answer."
)

INLINE_MARKER = re.compile(r"<\|[^|>]*\|>")
LEADING_ANSWER_LABEL = re.compile(r"(?i)^\s*answer\s*:\s*")
EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class RenderedAnswer:
    """Final artifact text plus observable workflow metadata."""

    text: str
    metadata: dict[str, object]


def render_answer(
    answer: KnowledgeAnswer,
    state: SearchState,
    *,
    requests: int,
    tokens: int,
) -> RenderedAnswer:
    """Render the answer with code-owned Gaps and Sources sections."""
    body = clean_text(answer.answer)
    gaps = list(answer.gaps)
    limits_hit: list[str] = []
    if state.search_limit_reached:
        gaps.append(SEARCH_LIMIT_GAP)
        limits_hit.append("search")

    evidence = retrieved_evidence(state)
    sections = [body]
    if gaps:
        sections.append("Gaps:\n" + "\n".join(f"- {gap}" for gap in gaps))
    if evidence:
        sources = "\n".join(
            _source_line(reference) for _, reference in evidence
        )
        sections.append(f"Sources:\n{sources}")
    else:
        sections.append(f"Limitation: {UNVERIFIED_LIMITATION}")

    metadata: dict[str, object] = {
        "loop": "typed_tool",
        "decision_source": "llm",
        "searches": state.searches,
        "search_limit": state.max_searches,
        "evidence_status": combined_evidence_status(state),
        "evidence": [
            {"search": index, **_reference_metadata(reference)}
            for index, reference in evidence
        ],
        "llm_requests": requests,
        "llm_tokens": tokens,
        "clarification_used": state.clarification_used,
        "limits_hit": limits_hit,
    }
    return RenderedAnswer(
        text="\n\n".join(sections).strip(), metadata=metadata
    )


def clean_text(text: str) -> str:
    """Strip inline documentation markers and a leading answer label."""
    without_markers = INLINE_MARKER.sub("", text)
    without_label = LEADING_ANSWER_LABEL.sub("", without_markers)
    return EXTRA_BLANK_LINES.sub("\n\n", without_label).strip()


def _source_line(reference: SearchReference) -> str:
    label = (
        reference.title
        or reference.document_id
        or reference.source
        or "Untitled source"
    )
    if reference.url:
        return f"- {label} — {reference.url}"
    return f"- {label}"


def _reference_metadata(reference: SearchReference) -> dict[str, object]:
    return {
        "source": reference.source,
        "document_id": reference.document_id,
        "title": reference.title,
        "url": reference.url,
        "support": reference.support,
    }
