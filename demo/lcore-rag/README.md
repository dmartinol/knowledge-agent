# LCORE image with the BYOK corpus

A second knowledge source for the demo: the synthetic Aurora Deploy corpus in
[demo/rag-corpus](../rag-corpus) indexed into a static FAISS store. LCORE serves
it alongside OKP, and `referenced_documents[].source` carries the store name so
the console can show which store answered.

Everything here is deterministic and offline at runtime: the index and the
embedding model are baked into the image, no ingest happens on start, and no
model is downloaded.

## What is committed

| File | Purpose |
| --- | --- |
| `Containerfile` | Derived LCORE image: pinned LCORE base, model copied from the pinned index tooling image, index copied read-only. |
| `generate-index.sh` | Regenerates `faiss_store.db` from the corpus with the pinned tooling. |
| `faiss_store.db` | SQLite + FAISS index, one vector-store id, one entry per corpus document. |

The generated database is committed on purpose. The generator asks OGX to
create the vector store, so the `vs_…` id is random per run; the chart must
carry that exact id in `lcore.rag.byok.vectorDbId`, and it must match the keys
inside the database. Committing the index keeps the chart value stable and lets
`tests/test_chart.py` prove the two agree.

## Regenerate the index

Run this only when the corpus changes.

```bash
./demo/lcore-rag/generate-index.sh
```

The script runs the pinned `quay.io/lightspeed-core/rag-content-cpu` image with
`-s llamastack-faiss`, which pins the same `ogx` version LCORE queries with, so
the SQLite key layout matches. It prints the new id:

```text
vector_db_id: vs_…
```

Then copy that value into `demo/chart/knowledge-agent/values.yaml` under
`lcore.rag.byok.vectorDbId` and re-run the chart tests. A stale id does not
fail loudly in LCORE: the store loads and every query returns nothing, which is
why the test asserts the id against the committed database keys.

## Why the model is copied, not downloaded

The base LCORE image ships `sentence-transformers` and `faiss-cpu` but no
embedding model, and the demo runs without egress to the model Hub. The
`Containerfile` copies `/rag-content/embeddings_model` out of the pinned
index-tooling image, so the query-time model is byte-identical to the one that
built the index and `SentenceTransformer` loads it from a local path.

`SentenceTransformer` is handed that directory, so the chart sets
`lcore.rag.byok.embeddingModel` to the path rather than to the Hugging Face id.

## Frontmatter and Sources

Every document starts with YAML frontmatter carrying `title` and an absolute
`url`. LCORE copies both into `referenced_documents`, and the `url` is required:
building a citation runs the value through a URL parser, and a bare filename
fails the whole `/v1/query` call. The demo corpus points at
`https://docs.aurora.invalid/…`, a domain that intentionally does not resolve,
so Sources are well-formed labels rather than working links. Point `url` at a
real page and regenerate the index if you want them to open something.

## Why it shares the file_search tool

When enabled, the chart appends the `rag_id` to `rag.retrieval.tool.sources`
next to `okp`, so one `file_search` covers both stores and
`referenced_documents[].source` names the store that answered. LCORE gives that
tool a single search mode, so the chart requires
`lcore.rag.searchMode=semantic`: FAISS has no keyword index, and `keyword` makes
it raise "Keyword search is not supported".

The store is deliberately not in `rag.retrieval.inline.sources`. Inline
retrieval runs on every request, so every answer — including a Red Hat question
— would carry Aurora chunks. With the tool, the model retrieves on demand.

LCORE's own tool loop is capped by `lcore.inference.maxInferIters` and
`maxToolCalls`. The demo model tends to re-query when the first pass looks
incomplete, and an uncapped loop turns one question into several minutes of
retrieval, past the agent's upstream timeout.

## Build the image

The chart pulls
`<internalRegistry>/<namespace>/knowledge-agent-lcore-rag:latest` unless
`lcore.rag.byok.image.repository` names a full repository.

```bash
export NS=knowledge-agent-demo
oc new-build --binary --strategy=docker --name=knowledge-agent-lcore-rag \
  --dockerfile=Containerfile -n "$NS"

tar --format=ustar -czf - -C demo/lcore-rag . \
  | oc start-build knowledge-agent-lcore-rag --from-archive=- --follow -n "$NS"
```

The context contains a SQLite file, so pack it as plain ustar: the builder
rejects the pax headers macOS `tar` emits by default.

`Containerfile`'s `LCORE_BASE_IMAGE` must stay equal to
`lcore.image.repository:tag` in the chart; a chart test enforces it.
