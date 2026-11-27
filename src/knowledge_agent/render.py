"""Deterministic rendering of the answer, gaps, sources, and metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

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
    retriever: str,
    source_base_internal: str = "",
    source_base_public: str = "",
) -> RenderedAnswer:
    """Render the answer with code-owned Gaps and Sources sections.

    When both source bases are configured, Source URLs are rebased from the
    internal base LCORE cites to the public one. Only those two strings are
    compared; the agent never resolves or discovers hosts.
    """
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
    bases = SourceBases(
        internal=source_base_internal, public=source_base_public
    )
    if evidence:
        sources = "\n".join(
            _source_line(reference, bases) for _, reference in evidence
        )
        sections.append(f"Sources:\n{sources}")
    else:
        sections.append(f"Limitation: {UNVERIFIED_LIMITATION}")

    limitation = None if evidence else UNVERIFIED_LIMITATION
    metadata: dict[str, object] = {
        "loop": "typed_tool",
        "decision_source": "llm",
        "retriever": retriever,
        "searches": state.searches,
        "search_limit": state.max_searches,
        "evidence_status": combined_evidence_status(state),
        "evidence": [
            {"search": index, **_reference_metadata(reference, bases)}
            for index, reference in evidence
        ],
        "gaps": gaps,
        "limitation": limitation,
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


@dataclass(frozen=True)
class SourceBases:
    """Internal and public bases used to rebase Source URLs."""

    internal: str = ""
    public: str = ""

    @property
    def active(self) -> bool:
        return bool(self.internal and self.public)


def rebase_source_url(url: str, bases: SourceBases) -> str:
    """Move ``url`` from the internal base origin to the public one.

    The URL is left untouched unless it shares the internal base's scheme,
    host, and port and its path falls under the internal base path. Path,
    query, and fragment are preserved, and the public base path is prepended
    when it has one.
    """
    if not bases.active:
        return url
    source = urlsplit(url)
    internal = urlsplit(bases.internal)
    if (source.scheme, source.netloc) != (internal.scheme, internal.netloc):
        return url
    prefix = internal.path.rstrip("/")
    if prefix and not source.path.startswith(prefix):
        return url
    remainder = source.path[len(prefix) :]
    public = urlsplit(bases.public)
    path = public.path.rstrip("/") + remainder
    return urlunsplit(
        (public.scheme, public.netloc, path, source.query, source.fragment)
    )


def _source_line(reference: SearchReference, bases: SourceBases) -> str:
    label = (
        reference.title
        or reference.document_id
        or reference.source
        or "Untitled source"
    )
    if reference.url:
        return f"- {label} — {rebase_source_url(reference.url, bases)}"
    return f"- {label}"


def _reference_metadata(
    reference: SearchReference, bases: SourceBases
) -> dict[str, object]:
    url = (
        rebase_source_url(reference.url, bases)
        if reference.url
        else reference.url
    )
    metadata: dict[str, object] = {
        "source": reference.source,
        "document_id": reference.document_id,
        "title": reference.title,
        "url": url,
        "support": reference.support,
    }
    if url != reference.url:
        metadata["upstream_url"] = reference.url
    return metadata
