from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pytest

from knowledge_agent.config import FollowUpPolicy
from knowledge_agent.lcore_client import (
    EvidenceStatus,
    LcoreEvidence,
    LcoreResult,
)
from knowledge_agent.workflow import (
    DEADLINE_LIMITATION,
    FOLLOW_UP_SUFFIX,
    NONE_LIMITATION,
    SKIPPED_LIMITATION,
    UNAVAILABLE_LIMITATION,
    WorkflowProgress,
    answer_looks_like_gap,
    build_result,
    clarification_metadata,
    clarification_question,
    compose_query,
    consolidate_evidence,
    consolidate_evidence_status,
    needs_clarification,
    policy_wants_follow_up,
    read_clarification_question,
    run_workflow,
    strip_process_narration,
)

GOOD_ANSWER = (
    "An OpenShift route exposes a service at a host name so external clients "
    "can reach it."
)


class FakeSearchClient:
    def __init__(self, results: Sequence[LcoreResult | Exception]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, str | None]] = []

    async def search(
        self, query: str, *, context_id: str | None = None
    ) -> LcoreResult:
        self.calls.append((query, context_id))
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


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


@pytest.mark.parametrize(
    "text",
    ["", "   ", "it", "this that", "hello", "thanks!", "why", "the pod"],
)
def test_underspecified_requests_need_clarification(text: str) -> None:
    assert needs_clarification(text)


@pytest.mark.parametrize(
    "text",
    [
        "How do OpenShift routes expose services?",
        "Explain pod disruption budgets in OpenShift",
        "What is a Kubernetes pod?",
    ],
)
def test_concrete_requests_do_not_need_clarification(text: str) -> None:
    assert not needs_clarification(text)


def test_clarification_question_for_greeting_and_fragment() -> None:
    assert clarification_question("hello") == "What would you like to search for?"
    assert clarification_question("it") == 'What would you like to know about "it"?'


def test_compose_query_puts_clarification_first_for_vague_requests() -> None:
    assert compose_query("it", "OpenShift route details") == (
        "OpenShift route details\n\nOriginal question: it"
    )
    assert compose_query("How do routes work?", "For OpenShift 4.16") == (
        "How do routes work?\n\nAdditional context from the caller: For OpenShift 4.16"
    )
    assert compose_query("How do routes work?", None) == "How do routes work?"


def test_clarification_metadata_round_trip() -> None:
    metadata = clarification_metadata("it")

    assert read_clarification_question(metadata) == "it"
    assert read_clarification_question(None) is None
    assert read_clarification_question({"knowledge_agent": {"phase": "done"}}) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I don't know.", True),
        ("I could not find information about that.", True),
        ("I wasn't able to find release notes for that version.", True),
        (
            "I don't have release notes for that version in the documentation.",
            True,
        ),
        ("The available documentation doesn't contain information.", True),
        (
            "Manifests do not include the field by default, so set it yourself.",
            False,
        ),
        ("Short answer.", True),
        (GOOD_ANSWER, False),
    ],
)
def test_answer_gap_heuristic(text: str, expected: bool) -> None:
    assert answer_looks_like_gap(text) is expected


@pytest.mark.parametrize(
    ("policy", "status", "text", "expected"),
    [
        (FollowUpPolicy.EVIDENCE, "none", GOOD_ANSWER, True),
        (FollowUpPolicy.EVIDENCE, "available", GOOD_ANSWER, False),
        (FollowUpPolicy.EVIDENCE, "unavailable", "I don't know.", False),
        (FollowUpPolicy.AUTO, "none", GOOD_ANSWER, True),
        (FollowUpPolicy.AUTO, "available", "I don't know.", False),
        (FollowUpPolicy.AUTO, "unavailable", "I don't know.", True),
        (FollowUpPolicy.AUTO, "unavailable", GOOD_ANSWER, False),
        (FollowUpPolicy.HEURISTIC, "available", "I don't know.", True),
        (FollowUpPolicy.HEURISTIC, "available", GOOD_ANSWER, False),
        (FollowUpPolicy.NEVER, "none", "I don't know.", False),
    ],
)
def test_policy_decisions(
    policy: FollowUpPolicy, status: EvidenceStatus, text: str, expected: bool
) -> None:
    result = _result(text, status=status)

    assert policy_wants_follow_up(policy, result) is expected


async def test_workflow_answers_without_follow_up_when_evidence_exists() -> None:
    fake = FakeSearchClient([_result(status="available")])

    result = await run_workflow(
        fake,
        policy=FollowUpPolicy.EVIDENCE,
        max_rounds=2,
        question="How do routes work?",
    )

    assert len(fake.calls) == 1
    assert result.searches == 1
    assert result.follow_up == "not_needed"


async def test_workflow_follows_up_on_empty_evidence() -> None:
    fake = FakeSearchClient(
        [_result(status="none"), _result(GOOD_ANSWER, status="none")]
    )

    result = await run_workflow(
        fake,
        policy=FollowUpPolicy.EVIDENCE,
        max_rounds=2,
        question="How do routes work?",
    )

    assert len(fake.calls) == 2
    assert fake.calls[0] == ("How do routes work?", None)
    query, context_id = fake.calls[1]
    assert query.startswith("How do routes work?")
    assert FOLLOW_UP_SUFFIX in query
    assert context_id == "lcore-ctx-1"
    assert result.searches == 2
    assert result.follow_up == "performed"


async def test_workflow_skips_follow_up_at_round_limit() -> None:
    fake = FakeSearchClient([_result(status="none")])

    result = await run_workflow(
        fake,
        policy=FollowUpPolicy.EVIDENCE,
        max_rounds=1,
        question="How do routes work?",
    )

    assert len(fake.calls) == 1
    assert result.follow_up == "skipped_limit"
    assert SKIPPED_LIMITATION in result.text


def test_renders_sources_only_from_structured_evidence() -> None:
    evidence = (
        LcoreEvidence(
            kind="chunk",
            title="Route concepts",
            url="https://docs.example/routes",
            chunk_id="chunk-1",
            excerpt="A route exposes a service at a host name.",
        ),
    )

    result = build_result(
        [_result(status="available", evidence=evidence)],
        policy=FollowUpPolicy.AUTO,
        searches=1,
        follow_up="not_needed",
    )

    assert result.text.startswith(GOOD_ANSWER)
    assert "Sources:" in result.text
    assert "- Route concepts — https://docs.example/routes" in result.text
    assert "A route exposes a service at a host name." in result.text
    assert result.metadata["evidence_status"] == "available"
    assert result.metadata["searches"] == 1
    assert result.metadata["follow_up_policy"] == "auto"
    assert result.metadata["evidence"] == [
        {
            "search": 1,
            "kind": "chunk",
            "source": None,
            "document_id": None,
            "chunk_id": "chunk-1",
            "url": "https://docs.example/routes",
            "title": "Route concepts",
            "excerpt": "A route exposes a service at a host name.",
            "score": None,
        }
    ]


def test_renders_limitations_for_missing_evidence() -> None:
    none_result = build_result(
        [_result(status="none")],
        policy=FollowUpPolicy.AUTO,
        searches=2,
        follow_up="performed",
    )
    unavailable_result = build_result(
        [_result(status="unavailable")],
        policy=FollowUpPolicy.AUTO,
        searches=1,
        follow_up="not_needed",
    )

    assert NONE_LIMITATION in none_result.text
    assert UNAVAILABLE_LIMITATION in unavailable_result.text


def test_deadline_limitation_is_appended_to_partial_result() -> None:
    result = build_result(
        [_result(status="available")],
        policy=FollowUpPolicy.AUTO,
        searches=1,
        follow_up="skipped_limit",
        extra_limitations=(DEADLINE_LIMITATION,),
    )

    assert result.follow_up == "skipped_limit"
    assert SKIPPED_LIMITATION in result.text
    assert DEADLINE_LIMITATION in result.text


async def test_progress_records_last_result() -> None:
    progress = WorkflowProgress()
    fake = FakeSearchClient([_result()])

    await run_workflow(
        fake,
        policy=FollowUpPolicy.AUTO,
        max_rounds=2,
        question="How do routes work?",
        progress=progress,
    )

    assert progress.searches == 1
    assert progress.last_result is not None


async def test_loop_uses_the_configured_round_cap() -> None:
    fake = FakeSearchClient([_result(status="none") for _ in range(3)])

    result = await run_workflow(
        fake,
        policy=FollowUpPolicy.EVIDENCE,
        max_rounds=3,
        question="How do routes work?",
    )

    assert len(fake.calls) == 3
    assert result.searches == 3
    assert result.follow_up == "performed"


async def test_zero_rounds_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_rounds"):
        await run_workflow(
            FakeSearchClient([]),
            policy=FollowUpPolicy.AUTO,
            max_rounds=0,
            question="How do routes work?",
        )



@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "I searched again. An OpenShift route exposes a service.",
            "An OpenShift route exposes a service.",
        ),
        (
            "I broadened the search across related terms: A route exposes a service.",
            "A route exposes a service.",
        ),
        (
            "I broadened the search.\n\nHere is what I found: A route exposes a service.",
            "A route exposes a service.",
        ),
        (
            "**Search results summary:** A route exposes a service.",
            "A route exposes a service.",
        ),
        (GOOD_ANSWER, GOOD_ANSWER),
        ("I don't know.", "I don't know."),
        ("I searched again.", "I searched again."),
        ("", ""),
    ],
)
def test_strip_process_narration(text: str, expected: str) -> None:
    assert strip_process_narration(text) == expected


def test_consolidation_unions_and_deduplicates_evidence_in_search_order() -> None:
    shared = LcoreEvidence(kind="document", document_id="doc-1", title="Doc 1")
    later = LcoreEvidence(kind="chunk", chunk_id="chunk-2", title="Chunk 2")
    first = _result(status="available", evidence=(shared,))
    second = _result(status="available", evidence=(shared, later))

    evidence = consolidate_evidence([first, second])

    assert [(entry.search, entry.item) for entry in evidence] == [
        (1, shared),
        (2, later),
    ]
    assert consolidate_evidence_status([first, second], evidence) == "available"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (("none",), "none"),
        (("none", "none"), "none"),
        (("none", "unavailable"), "unavailable"),
        (("unavailable",), "unavailable"),
    ],
)
def test_consolidated_status_without_evidence(
    statuses: Sequence[EvidenceStatus], expected: EvidenceStatus
) -> None:
    results = [_result(status=status) for status in statuses]

    assert consolidate_evidence(results) == ()
    assert consolidate_evidence_status(results, ()) == expected


def test_build_result_uses_cleaned_last_answer_and_all_evidence() -> None:
    first_evidence = LcoreEvidence(
        kind="document", document_id="doc-1", title="Release notes"
    )
    second_evidence = LcoreEvidence(
        kind="chunk",
        chunk_id="chunk-2",
        title="RHEL 11 overview",
        url="https://docs.example/rhel-11",
    )
    results = [
        _result(status="available", evidence=(first_evidence,)),
        _result(
            "I broadened the search. RHEL 11 is available as a beta.",
            status="available",
            evidence=(second_evidence,),
        ),
    ]

    result = build_result(
        results,
        policy=FollowUpPolicy.AUTO,
        searches=2,
        follow_up="performed",
    )

    assert result.text.startswith("RHEL 11 is available as a beta.")
    assert "I broadened the search" not in result.text
    assert "- Release notes" in result.text
    assert "- RHEL 11 overview — https://docs.example/rhel-11" in result.text
    evidence_metadata = cast(list[dict[str, object]], result.metadata["evidence"])
    assert [entry["search"] for entry in evidence_metadata] == [1, 2]
    assert result.evidence_status == "available"
    assert result.searches == 2


async def test_progress_collects_every_result_in_order() -> None:
    progress = WorkflowProgress()
    first = _result(status="none")
    second = _result(GOOD_ANSWER, status="none")
    fake = FakeSearchClient([first, second])

    await run_workflow(
        fake,
        policy=FollowUpPolicy.EVIDENCE,
        max_rounds=2,
        question="How do routes work?",
        progress=progress,
    )

    assert progress.results == [first, second]
    assert progress.last_result == second
