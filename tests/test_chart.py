from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

CHART = (
    Path(__file__).resolve().parents[1]
    / "demo"
    / "chart"
    / "knowledge-agent"
)

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm is not installed"
)

BASE_ARGS = (
    "--set",
    "agent.llm.baseUrl=http://model.test/v1",
    "--set",
    "agent.llm.model=vendor/model",
    "--set",
    "secrets.existingSecret=test-secret",
)


def _render(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["helm", "template", "test", str(CHART), *BASE_ARGS, *extra],
        capture_output=True,
        text=True,
        check=False,
    )


def _rendered(*extra: str) -> str:
    result = _render(*extra)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_default_retriever_is_rest_with_the_in_cluster_url() -> None:
    output = _rendered()

    assert 'LCORE_RETRIEVER: "rest"' in output
    assert (
        'LCORE_REST_URL: "http://test-knowledge-agent-lcore:8080"' in output
    )
    assert (
        'LCORE_AGENT_CARD_URL: "http://test-knowledge-agent-lcore:8080'
        '/.well-known/agent-card.json"' in output
    )


def test_a2a_retriever_renders_both_urls() -> None:
    output = _rendered("--set", "agent.retriever=a2a")

    assert 'LCORE_RETRIEVER: "a2a"' in output
    assert 'LCORE_REST_URL: "http://test-knowledge-agent-lcore:8080"' in output


def test_external_lcore_url_is_derived_without_a_trailing_slash() -> None:
    output = _rendered(
        "--set",
        "lcore.enabled=false",
        "--set",
        "lcore.externalUrl=http://lcore.example:8080/",
    )

    assert 'LCORE_REST_URL: "http://lcore.example:8080"' in output
    assert (
        'LCORE_AGENT_CARD_URL: "http://lcore.example:8080'
        '/.well-known/agent-card.json"' in output
    )


def test_unknown_retriever_fails_the_render() -> None:
    result = _render("--set", "agent.retriever=grpc")

    assert result.returncode != 0
    assert "agent.retriever must be 'a2a' or 'rest'" in result.stderr
