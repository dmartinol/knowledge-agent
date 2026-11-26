from __future__ import annotations

from typing import Any, cast

from knowledge_agent.lcore_client import LcoreEvidence, LcoreResult
from knowledge_agent.loop import SearchState
from knowledge_agent.reasoning import KnowledgeAnswer
from knowledge_agent.render import (
    SEARCH_LIMIT_GAP,
    UNVERIFIED_LIMITATION,
    clean_text,
    render_answer,
)


def _state(
    *results: LcoreResult, max_searches: int = 2, searches: int | None = None
) -> SearchState:
    state = SearchState(client=object(), max_searches=max_searches)  # type: ignore[arg-type]
    state.results = list(results)
    state.searches = len(results) if searches is None else searches
    return state


def _result(*evidence: LcoreEvidence, status: str = "available") -> LcoreResult:
    return LcoreResult(
        text="material",
        task_id=None,
        context_id=None,
        evidence=tuple(evidence),
        evidence_status=status,  # type: ignore[arg-type]
    )


def _document(
    document_id: str, *, support: str | None = "retrieved", title: str = "Doc"
) -> LcoreEvidence:
    return LcoreEvidence(
        kind="document",
        source="okp",
        document_id=document_id,
        title=title,
        url=f"https://docs.example/{document_id}",
        support=support,  # type: ignore[arg-type]
    )


def test_answer_is_rendered_with_gaps_and_sources_in_order() -> None:
    state = _state(_result(_document("doc-1", title="Route concepts")))
    answer = KnowledgeAnswer(answer="Routes expose services.", gaps=["No install steps."])

    rendered = render_answer(
        answer, state, requests=3, tokens=120, retriever="a2a"
    )

    assert rendered.text == (
        "Routes expose services.\n\n"
        "Gaps:\n- No install steps.\n\n"
        "Sources:\n- Route concepts — https://docs.example/doc-1"
    )
    assert rendered.metadata["searches"] == 1
    assert rendered.metadata["search_limit"] == 2
    assert rendered.metadata["retriever"] == "a2a"
    assert rendered.metadata["evidence"] == [
        {
            "search": 1,
            "source": "okp",
            "document_id": "doc-1",
            "title": "Route concepts",
            "url": "https://docs.example/doc-1",
            "support": "retrieved",
        }
    ]
    assert rendered.metadata["limits_hit"] == []
    assert rendered.metadata["gaps"] == ["No install steps."]
    assert rendered.metadata["limitation"] is None


def test_search_limit_adds_a_gap_and_limit_metadata() -> None:
    state = _state(_result(_document("doc-1")), max_searches=1)

    rendered = render_answer(
        KnowledgeAnswer(answer="Answer."),
        state,
        requests=2,
        tokens=10,
        retriever="a2a",
    )

    assert SEARCH_LIMIT_GAP in rendered.text
    assert rendered.metadata["limits_hit"] == ["search"]
    assert rendered.metadata["gaps"] == [SEARCH_LIMIT_GAP]
    assert rendered.metadata["limitation"] is None


def test_no_retrieved_references_are_labeled_unverified() -> None:
    state = _state(_result(_document("doc-1", support="cited")))

    rendered = render_answer(
        KnowledgeAnswer(answer="Answer."),
        state,
        requests=2,
        tokens=10,
        retriever="a2a",
    )

    assert "Sources:" not in rendered.text
    assert UNVERIFIED_LIMITATION in rendered.text
    assert rendered.metadata["evidence"] == []
    assert rendered.metadata["evidence_status"] == "available"
    assert rendered.metadata["gaps"] == []
    assert rendered.metadata["limitation"] == UNVERIFIED_LIMITATION


def test_references_are_deduplicated_across_searches() -> None:
    state = _state(
        _result(_document("doc-1")),
        _result(_document("doc-1", title="Duplicate"), _document("doc-2")),
    )

    rendered = render_answer(
        KnowledgeAnswer(answer="Answer."),
        state,
        requests=4,
        tokens=20,
        retriever="rest",
    )

    entries = cast(list[dict[str, Any]], rendered.metadata["evidence"])
    document_ids = [entry["document_id"] for entry in entries]
    assert document_ids == ["doc-1", "doc-2"]
    assert entries[1]["search"] == 2
    assert rendered.metadata["retriever"] == "rest"


def test_clean_text_strips_markers_and_answer_labels() -> None:
    text = "Answer: A pod <|/documentation/pods|>is the smallest unit.\n\n\n\nNext."

    assert clean_text(text) == "A pod is the smallest unit.\n\nNext."
