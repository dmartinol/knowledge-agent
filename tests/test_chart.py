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


def _env_block(output: str, name: str) -> str:
    """Return a rendered env entry together with its indented children."""
    lines = output[output.index(f"- name: {name}") :].splitlines()
    block = [lines[0]]
    for line in lines[1:]:
        if not line.startswith(" " * 14):
            break
        block.append(line)
    return "\n".join(block)


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


def test_lcore_reads_the_internal_rhokp_url_from_the_values() -> None:
    block = _env_block(_rendered(), "RH_SERVER_OKP")

    assert 'value: "http://rhokp.rhokp.svc.cluster.local:8080"' in block
    assert "secretKeyRef:" not in block


def test_internal_rhokp_url_is_overridable() -> None:
    block = _env_block(
        _rendered("--set", "rhokp.internalUrl=http://rhokp.svc:8080/"),
        "RH_SERVER_OKP",
    )

    assert 'value: "http://rhokp.svc:8080/"' in block


def test_public_rhokp_url_goes_to_the_agent_not_lcore() -> None:
    output = _rendered(
        "--set", "rhokp.publicUrl=https://rhokp-rhokp.apps.example.com"
    )

    assert (
        'SOURCE_BASE_INTERNAL_URL: "http://rhokp.rhokp.svc.cluster.local:8080"'
        in output
    )
    assert (
        'SOURCE_BASE_PUBLIC_URL: "https://rhokp-rhokp.apps.example.com"'
        in output
    )
    assert (
        'value: "https://rhokp-rhokp.apps.example.com"' not in output
    )


def test_without_a_public_url_the_agent_keeps_lcore_urls() -> None:
    output = _rendered()

    assert "SOURCE_BASE_PUBLIC_URL" not in output
