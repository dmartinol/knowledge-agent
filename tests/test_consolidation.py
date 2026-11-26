from __future__ import annotations

from collections.abc import Sequence

import pytest

from knowledge_agent.consolidation import (
    CONSOLIDATION_TEMPLATE_VERSION,
    build_consolidation_prompt,
    consolidate_answer,
)
from knowledge_agent.lcore_client import LcoreResult


def _result(text: str, *, context_id: str = "lcore-ctx") -> LcoreResult:
    return LcoreResult(
        text=text,
        task_id="lcore-task",
        context_id=context_id,
        evidence_status="unavailable",
    )


class FakeClient:
    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.calls: list[tuple[str, str | None]] = []

    async def search(
        self, query: str, *, context_id: str | None = None
    ) -> LcoreResult:
        self.calls.append((query, context_id))
        return _result(self._reply, context_id=context_id or "lcore-ctx")


def test_prompt_is_deterministic_and_self_contained() -> None:
    results: Sequence[LcoreResult] = [
        _result("First answer text."),
        _result("Second answer text."),
    ]

    prompt = build_consolidation_prompt("How do routes work?", results)

    assert prompt == build_consolidation_prompt("How do routes work?", results)
    assert "Original question:\nHow do routes work?" in prompt
    assert "[Search result 1]\nFirst answer text." in prompt
    assert "[Search result 2]\nSecond answer text." in prompt
    assert "<<<MATERIAL" in prompt
    assert "MATERIAL>>>" in prompt


def test_prompt_pins_the_output_contract() -> None:
    prompt = build_consolidation_prompt("q " * 3, [_result("a")])

    assert "Start directly with the answer" in prompt
    assert "Do not mention searches, attempts, rounds" in prompt
    assert "Do not include a Sources, References, or Citations section" in prompt
    assert 'section titled "Gaps:"' in prompt
    assert "use only the material above" in prompt
    assert CONSOLIDATION_TEMPLATE_VERSION == "v1"


def test_prompt_requires_results_and_question() -> None:
    with pytest.raises(ValueError, match="at least one result"):
        build_consolidation_prompt("question", [])
    with pytest.raises(ValueError, match="requires a question"):
        build_consolidation_prompt("   ", [_result("a")])


async def test_consolidate_answer_reuses_conversation_and_strips_narration() -> None:
    client = FakeClient("I broadened the search. Final route answer.")

    text = await consolidate_answer(
        client,
        question="How do routes work?",
        results=[
            _result("First.", context_id="lcore-ctx-1"),
            _result("Second.", context_id="lcore-ctx-2"),
        ],
    )

    assert text == "Final route answer."
    assert len(client.calls) == 1
    assert client.calls[0][1] == "lcore-ctx-2"


async def test_consolidate_answer_returns_none_for_blank_reply() -> None:
    client = FakeClient("   ")

    text = await consolidate_answer(
        client,
        question="How do routes work?",
        results=[_result("First.")],
    )

    assert text is None
