"""Bounded decide-search-observe workflow for knowledge questions."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol

from knowledge_agent.config import FollowUpPolicy
from knowledge_agent.lcore_client import (
    EvidenceKey,
    EvidenceStatus,
    LcoreEvidence,
    LcoreResult,
    evidence_key,
)

WORKFLOW_METADATA_KEY = "knowledge_agent"
CLARIFICATION_PHASE = "awaiting_clarification"

GAP_PATTERNS = (
    r"i (?:do not|don't) know",
    r"i (?:do not|don't) have (?:any )?(?:information|documentation|details|release notes)",
    r"i (?:still |also |just )?(?:could not|couldn't|can not|cannot|can't) (?:find|locate)",
    r"i (?:was not|wasn't|am not) able to (?:find|locate|answer)",
    r"(?:was|were|is|are) unable to (?:find|locate|answer)",
    r"unable to (?:find|locate|answer)",
    r"(?:cannot|can not|can't) answer",
    r"no (?:information|documentation|details)",
    r"not (?:enough|sufficient) information",
    r"insufficient information",
    r"the (?:available )?(?:documentation|sources?) (?:does not|doesn't|do not|don't) (?:contain|include|cover|mention)",
    r"i(?:'m| am) not sure",
)
NARRATION_PREFIXES = (
    "i searched again",
    "i'll search again",
    "i will search again",
    "i broadened",
    "i expanded the search",
    "i ran another search",
    "i ran a follow-up search",
    "i performed another search",
    "i performed a follow-up search",
    "after searching again",
    "after broadening",
    "here's what the searches turned up",
    "here is what the searches turned up",
    "here's what my searches turned up",
    "here is what my searches turned up",
    "here's what i found",
    "here is what i found",
    "search results summary",
    "based on the follow-up search",
    "based on the additional search",
)
PRONOUN_TOKENS = frozenset(
    {
        "it",
        "this",
        "that",
        "these",
        "those",
        "they",
        "them",
        "he",
        "she",
        "him",
        "her",
        "one",
        "ones",
    }
)
GREETINGS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "thanks",
        "thank you",
    }
)

MIN_ANSWER_LENGTH = 40
EXCERPT_LIMIT = 200
FOLLOW_UP_SUFFIX = (
    "Broaden the search to closely related terminology and official product "
    "documentation, then answer the original question directly without "
    "describing the search steps."
)
DEADLINE_LIMITATION = (
    "The workflow deadline was reached before the follow-up search could run."
)
UNAVAILABLE_LIMITATION = (
    "No structured source evidence was returned by the upstream service; "
    "this answer is unverified."
)
NONE_LIMITATION = "No supporting evidence was returned for this answer."
SKIPPED_LIMITATION = (
    "A follow-up search was skipped because the workflow round limit was reached."
)

FollowUpStatus = Literal["performed", "not_needed", "skipped_limit", "disabled"]
ConsolidationStatus = Literal["llm", "fallback", "skipped_single_result"]

_TOKEN_RE = re.compile(r"[a-z']+")
_GAP_RE = re.compile("|".join(f"(?:{pattern})" for pattern in GAP_PATTERNS))
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")
_LEADING_MARKERS_RE = re.compile(r"^[\s>#*_\-•]+")


class SearchClient(Protocol):
    """Minimal upstream surface the workflow depends on."""

    async def search(
        self, query: str, *, context_id: str | None = None
    ) -> LcoreResult: ...


@dataclass(frozen=True)
class WorkflowEvidence:
    """One upstream evidence item plus the search round that produced it."""

    item: LcoreEvidence
    search: int


@dataclass(frozen=True)
class WorkflowResult:
    """Final workflow outcome with only LCORE-supported evidence."""

    text: str
    evidence: tuple[WorkflowEvidence, ...]
    evidence_status: EvidenceStatus
    searches: int
    follow_up: FollowUpStatus
    lcore_context_id: str | None
    policy: FollowUpPolicy
    consolidation: ConsolidationStatus = "skipped_single_result"

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "evidence_status": self.evidence_status,
            "evidence": [
                {"search": entry.search, **asdict(entry.item)}
                for entry in self.evidence
            ],
            "searches": self.searches,
            "follow_up": self.follow_up,
            "follow_up_policy": self.policy.value,
            "consolidation": self.consolidation,
        }


@dataclass
class WorkflowProgress:
    """Mutable progress so a deadline can still return an earlier answer."""

    results: list[LcoreResult] = field(default_factory=list)
    searches: int = 0
    follow_up: FollowUpStatus = "not_needed"

    @property
    def last_result(self) -> LcoreResult | None:
        """Most recent observation, or None before the first search."""
        return self.results[-1] if self.results else None


def _normalized(text: str) -> str:
    return " ".join(text.replace("’", "'").lower().split())


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def needs_clarification(text: str) -> bool:
    """Return True only for clearly underspecified requests."""
    stripped = text.strip()
    if not stripped:
        return True
    lowered = _normalized(stripped).strip(" .!?")
    if lowered in GREETINGS:
        return True
    tokens = _tokens(stripped)
    if len(tokens) < 3:
        return True
    return all(token in PRONOUN_TOKENS for token in tokens)


def clarification_question(text: str) -> str:
    """Build the single clarification question for an underspecified request."""
    stripped = text.strip()
    lowered = _normalized(stripped).strip(" .!?")
    if not stripped or lowered in GREETINGS:
        return "What would you like to search for?"
    return f'What would you like to know about "{stripped}"?'


def compose_query(question: str, clarification: str | None) -> str:
    """Combine the original request with the caller's clarification."""
    base = question.strip()
    extra = (clarification or "").strip()
    if not extra:
        return base
    if needs_clarification(base):
        return f"{extra}\n\nOriginal question: {base}"
    return f"{base}\n\nAdditional context from the caller: {extra}"


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


def answer_looks_like_gap(text: str) -> bool:
    """Conservative text heuristic used only when evidence is unavailable."""
    if len(text.strip()) < MIN_ANSWER_LENGTH:
        return True
    return _GAP_RE.search(_normalized(text)) is not None


def policy_wants_follow_up(
    policy: FollowUpPolicy, result: LcoreResult
) -> bool:
    """Decide from one observation whether another search could help."""
    if policy is FollowUpPolicy.NEVER:
        return False
    if policy is FollowUpPolicy.EVIDENCE:
        return result.evidence_status == "none"
    if policy is FollowUpPolicy.HEURISTIC:
        return answer_looks_like_gap(result.text)
    if result.evidence_status == "available":
        return False
    if result.evidence_status == "none":
        return True
    return answer_looks_like_gap(result.text)


async def run_workflow(
    client: SearchClient,
    *,
    policy: FollowUpPolicy,
    max_rounds: int,
    question: str,
    clarification: str | None = None,
    progress: WorkflowProgress | None = None,
) -> WorkflowResult:
    """Run the bounded decide-search-observe loop until it settles."""
    progress = progress if progress is not None else WorkflowProgress()
    query = compose_query(question, clarification)
    if not query:
        raise ValueError("question must not be empty")
    if max_rounds < 1:
        raise ValueError("max_rounds must be at least 1")

    result: LcoreResult | None = None
    follow_up: FollowUpStatus = "not_needed"
    while progress.searches < max_rounds:
        if progress.searches == 0:
            next_query = query
            context_id = None
        else:
            next_query = f"{query}\n\n{FOLLOW_UP_SUFFIX}"
            context_id = (
                progress.last_result.context_id
                if progress.last_result is not None
                else None
            )

        result = await client.search(next_query, context_id=context_id)
        progress.searches += 1
        progress.results.append(result)

        if not policy_wants_follow_up(policy, result):
            if policy is FollowUpPolicy.NEVER:
                follow_up = "disabled"
            break
        if progress.searches >= max_rounds:
            if follow_up != "performed":
                follow_up = "skipped_limit"
            break
        follow_up = "performed"

    if result is None:
        raise ValueError("workflow completed without a search result")

    progress.follow_up = follow_up
    return build_result(
        progress.results,
        policy=policy,
        searches=progress.searches,
        follow_up=follow_up,
    )


def build_result(
    results: Sequence[LcoreResult],
    *,
    policy: FollowUpPolicy,
    searches: int,
    follow_up: FollowUpStatus,
    extra_limitations: Sequence[str] = (),
    answer_text: str | None = None,
    consolidation: ConsolidationStatus = "skipped_single_result",
) -> WorkflowResult:
    """Consolidate every search result into one deterministic artifact."""
    if not results:
        raise ValueError("build_result requires at least one search result")
    latest = results[-1]
    evidence = consolidate_evidence(results)
    evidence_status = consolidate_evidence_status(results, evidence)
    body = answer_text.strip() if answer_text is not None else ""
    parts = [body or strip_process_narration(latest.text)]
    if evidence_status == "available" and evidence:
        parts.append(_sources_section(evidence))
    elif evidence_status == "none":
        parts.append(NONE_LIMITATION)
    else:
        parts.append(UNAVAILABLE_LIMITATION)
    if follow_up == "skipped_limit":
        parts.append(SKIPPED_LIMITATION)
    parts.extend(extra_limitations)
    return WorkflowResult(
        text="\n\n".join(part for part in parts if part),
        evidence=evidence,
        evidence_status=evidence_status,
        searches=searches,
        follow_up=follow_up,
        lcore_context_id=latest.context_id,
        policy=policy,
        consolidation=consolidation,
    )


def consolidate_evidence(
    results: Sequence[LcoreResult],
) -> tuple[WorkflowEvidence, ...]:
    """Union of evidence across searches, in search order, deduplicated."""
    merged: list[WorkflowEvidence] = []
    seen: set[EvidenceKey] = set()
    for search, result in enumerate(results, start=1):
        for item in result.evidence:
            key = evidence_key(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(WorkflowEvidence(item=item, search=search))
    return tuple(merged)


def consolidate_evidence_status(
    results: Sequence[LcoreResult],
    evidence: Sequence[WorkflowEvidence],
) -> EvidenceStatus:
    """Aggregate evidence status without claiming evidence that is absent."""
    if evidence:
        return "available"
    if results and all(result.evidence_status == "none" for result in results):
        return "none"
    return "unavailable"


def strip_process_narration(text: str) -> str:
    """Remove leading sentences that describe the search process itself."""
    body = text.strip()
    while body:
        start = _leading_marker_end(body)
        lowered = body[start:].lower()
        prefix = next(
            (phrase for phrase in NARRATION_PREFIXES if lowered.startswith(phrase)),
            None,
        )
        if prefix is None:
            return body
        remainder = body[start + len(prefix) :]
        colon = remainder.find(":")
        sentence_end = _first_sentence_end(remainder)
        if colon != -1 and (sentence_end is None or colon < sentence_end):
            cut = start + len(prefix) + colon + 1
        elif sentence_end is not None:
            cut = start + len(prefix) + sentence_end + 1
        else:
            return body
        candidate = _clean_fragment(body[cut:])
        if not candidate:
            return body
        body = candidate
    return body


def _leading_marker_end(text: str) -> int:
    match = _LEADING_MARKERS_RE.match(text)
    return match.end() if match else 0


def _first_sentence_end(text: str) -> int | None:
    match = _SENTENCE_END_RE.search(text)
    return match.start() if match else None


def _clean_fragment(text: str) -> str:
    return text.strip().strip("*_").strip()


def _sources_section(evidence: Sequence[WorkflowEvidence]) -> str:
    lines = ["Sources:"]
    for entry in evidence:
        item = entry.item
        label = item.title or item.document_id or item.chunk_id or item.url
        if not label:
            continue
        line = f"- {label}"
        if item.url and item.url != label:
            line = f"{line} — {item.url}"
        if item.excerpt:
            line = f"{line}\n  {_truncate(item.excerpt)}"
        lines.append(line)
    return "\n".join(lines)


def _truncate(text: str) -> str:
    excerpt = " ".join(text.split())
    if len(excerpt) <= EXCERPT_LIMIT:
        return excerpt
    return f"{excerpt[: EXCERPT_LIMIT - 1].rstrip()}…"
