#!/usr/bin/env bash
# Rebuild faiss_store.db from demo/rag-corpus with the pinned index tooling.
#
# Run this only when the corpus changes: the generated vector store id is baked
# into the chart values, and a fresh run produces a different one.
set -euo pipefail

RAG_CONTENT_IMAGE="${RAG_CONTENT_IMAGE:-quay.io/lightspeed-core/rag-content-cpu:dev-20261102-d45a628}"
RAG_ID="${RAG_ID:-aurora-docs}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-sentence-transformers/all-mpnet-base-v2}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
corpus="${CORPUS:-$here/../rag-corpus}"
output="$(mktemp -d "${TMPDIR:-/tmp}/aurora-index.XXXXXX")"

platform=()
if [ "$(uname -s)" = "Darwin" ]; then
  # The published image is linux/amd64 only.
  platform=(--platform linux/amd64)
fi

podman run --rm "${platform[@]}" \
  -v "$corpus":/input:ro \
  -v "$output":/output \
  "$RAG_CONTENT_IMAGE" \
  python scripts/generate_embeddings.py \
  -f /input \
  -o /output \
  -i "$RAG_ID" \
  -s llamastack-faiss \
  -m "$EMBEDDING_MODEL"

cp "$output/faiss_store.db" "$here/"

echo
echo "Index written to $here/faiss_store.db"
echo "Copy this id into lcore.rag.byok.vectorDbId:"
grep -E 'vector_db_id|rag_id' "$output/lightspeed-stack.yaml"
