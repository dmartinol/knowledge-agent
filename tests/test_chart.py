from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[1] / "demo"
CHART = DEMO / "chart" / "knowledge-agent"
RAG_IMAGE = DEMO / "lcore-rag"
CORPUS = DEMO / "rag-corpus"

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


BYOK = ("--set", "lcore.rag.byok.enabled=true")

EXPECTED_CORPUS = {
    "aurora-cli.md": "Aurora CLI reference",
    "aurora-install.md": "Installing Aurora Deploy",
    "aurora-networking.md": "Aurora networking",
    "aurora-overview.md": "Aurora Deploy overview",
    "aurora-quotas.md": "Aurora project quotas",
    "aurora-release-notes.md": "Aurora Deploy release notes",
    "aurora-tls.md": "Aurora TLS handling",
}


def test_byok_disabled_keeps_the_okp_only_configuration() -> None:
    output = _rendered()

    assert "rag.byok" not in output
    assert "faiss" not in output
    assert "/app-root/lcore-rag" not in output
    assert "lcore-rag:latest" not in output


def test_byok_enabled_renders_the_store_and_its_tool_source() -> None:
    output = _rendered(*BYOK, "--set", "lcore.rag.searchMode=semantic")

    assert "      byok:" in output
    assert 'rag_id: "aurora-docs"' in output
    assert "backend: faiss" in output
    assert 'embedding_model: "/app-root/embeddings/all-mpnet-base-v2"' in output
    assert "embedding_dimension: 768" in output
    assert 'db_path: "/tmp/lcore-rag/faiss_store.db"' in output
    tool = output[output.index("        tool:") : output.index("      byok:")]
    assert '- "okp"' in tool
    assert '- "aurora-docs"' in tool
    assert "inline:" not in output
    assert "search_mode: semantic" in output


def test_byok_requires_vector_search_for_the_shared_tool() -> None:
    result = _render(*BYOK, "--set", "lcore.rag.searchMode=keyword")

    assert result.returncode != 0
    assert "requires lcore.rag.searchMode=semantic" in result.stderr


def test_lcore_tool_loop_is_bounded() -> None:
    output = _rendered()

    assert "      max_infer_iters: 5" in output
    assert "      max_tool_calls: 3" in output


def test_workflow_timeouts_outlive_one_bounded_lcore_query() -> None:
    output = _rendered()

    assert 'WORKFLOW_UPSTREAM_TIMEOUT_SECONDS: "150"' in output
    assert 'WORKFLOW_TASK_DEADLINE_SECONDS: "210"' in output
    assert 'haproxy.router.openshift.io/timeout: "240s"' in output


def test_byok_enabled_switches_the_lcore_image() -> None:
    output = _rendered(*BYOK)

    assert (
        "image: image-registry.openshift-image-registry.svc:5000"
        "/knowledge-agent-demo/knowledge-agent-lcore-rag:latest" in output
    )
    assert "imagePullPolicy: Always" in output


def test_byok_enabled_materialises_the_index_at_startup() -> None:
    block = _rendered(*BYOK)

    assert "mkdir -p /tmp/data \"/tmp/lcore-rag\"" in block
    assert (
        "cp /app-root/lcore-rag/faiss_store.db \"/tmp/lcore-rag/faiss_store.db\""
        in block
    )


def test_byok_image_tag_survives_reused_release_values() -> None:
    output = _rendered(*BYOK, "--set", "lcore.rag.byok.image.tag=")

    assert "knowledge-agent-lcore-rag:latest" in output


def test_byok_requires_the_chart_managed_lcore() -> None:
    result = _render(
        "--set",
        "lcore.enabled=false",
        "--set",
        "lcore.externalUrl=http://lcore.example:8080",
        "--set",
        "lcore.rag.byok.enabled=true",
    )

    assert result.returncode != 0
    assert "requires lcore.enabled=true" in result.stderr


def _index_record(store_id: str) -> dict:
    """Return the vector store record the committed index carries."""
    database = RAG_IMAGE / "faiss_store.db"
    key = f"vector_io::faiss:vector_stores:v3::{store_id}"
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "select value from kvstore where key = ?", (key,)
        ).fetchone()

    assert row is not None, f"{key} is missing from the committed index"
    return json.loads(row[0])


def test_committed_index_carries_the_rendered_store_id() -> None:
    output = _rendered(*BYOK)
    store_id = re.search(r'vector_db_id: "([^"]+)"', output)
    assert store_id is not None

    database = RAG_IMAGE / "faiss_store.db"
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        keys = {row[0] for row in connection.execute("select key from kvstore")}

    assert f"vector_io::faiss:vector_stores:v3::{store_id.group(1)}" in keys
    assert f"vector_io::faiss:faiss_index:v3::{store_id.group(1)}" in keys


def test_committed_index_describes_the_rendered_store() -> None:
    output = _rendered(*BYOK)
    store_id = re.search(r'vector_db_id: "([^"]+)"', output)
    rag_id = re.search(r'rag_id: "([^"]+)"', output)
    model = re.search(r'embedding_model: "([^"]+)"', output)
    dimension = re.search(r"embedding_dimension: (\d+)", output)
    assert store_id is not None
    assert rag_id is not None
    assert model is not None
    assert dimension is not None

    record = _index_record(store_id.group(1))
    assert record["vector_store_name"] == rag_id.group(1)
    assert record["embedding_dimension"] == int(dimension.group(1))
    assert record["embedding_model"].rsplit("/", 1)[-1] == (
        model.group(1).rsplit("/", 1)[-1]
    )


def test_corpus_is_the_expected_document_set() -> None:
    documents = {path.name: path for path in CORPUS.glob("*.md")}

    assert set(documents) == set(EXPECTED_CORPUS)
    for name, title in EXPECTED_CORPUS.items():
        lines = documents[name].read_text().splitlines()
        assert lines[0] == "---"
        front_matter = lines[1 : lines.index("---", 1)]
        assert f"title: {title}" in front_matter
        assert f"# {title}" in lines


def test_corpus_documents_advertise_an_absolute_source_url() -> None:
    for path in CORPUS.glob("*.md"):
        lines = path.read_text().splitlines()
        front_matter = lines[1 : lines.index("---", 1)]
        urls = [line for line in front_matter if line.startswith("url: ")]

        assert urls == [urls[0]], path.name
        assert urls[0].startswith("url: https://"), path.name


def test_containerfile_pins_the_chart_lcore_image() -> None:
    output = _rendered()
    image = re.search(
        r"image: (quay\.io/lightspeed-core/lightspeed-stack:\S+)", output
    )
    containerfile = (RAG_IMAGE / "Containerfile").read_text()
    pinned = re.search(r"^ARG LCORE_BASE_IMAGE=(\S+)$", containerfile, re.MULTILINE)
    assert image is not None
    assert pinned is not None

    assert pinned.group(1) == image.group(1)
