# Knowledge Search Agent

A proof of concept for an A2A agent that provides evidence-aware knowledge search, using Lightspeed Core Stack (LCORE) as a service.

## Initial architecture

This repository owns the Knowledge Search agent and its A2A interface. It calls LCORE through LCORE's A2A interface for model and retrieval work.

- The agent owns a bounded query workflow: decide when to clarify, form follow-up queries, assess returned evidence, and communicate an answer or an evidence gap.
- LCORE owns model serving, retrieval execution, and the administrator-configured OKP and BYOK sources and credentials.
- Callers cannot select vector stores or change LCORE configuration. The agent must not forward caller-provided source identifiers to LCORE.
- The query path uses A2A between the agent and LCORE. The agent does not import LCORE internals or connect directly to its vector databases.

See [the architecture notes](docs/architecture.md) and [open questions](docs/open-questions.md) before implementing the runtime.

## Upstream contract

[The LCORE A2A contract report](docs/lcore-a2a-contract.md) records what the local LCORE deployment actually returns: retrieval runs, but the A2A artifact carries only the final answer text — no `rag_chunks` or `referenced_documents` — while the REST query endpoint does expose them. The missing A2A evidence contract remains an open upstream gap.

Consequences for this agent: it sends no message metadata (LCORE would honor `model`, `provider`, and `vector_store_ids` from the caller), it never presents inline `<|/documentation/...|>` markers as citations, and it enforces local limits because the A2A path applies no upstream quota accounting.

## LCORE client

`knowledge_agent.lcore_client.LcoreClient` discovers the Agent Card at `LCORE_AGENT_CARD_URL`, caches it, and sends one non-streaming `message/send` per `search()` call. Requests carry no message metadata, so callers cannot select a model, provider, or vector store. Failures are normalized to `LcoreError` categories, and the per-call timeout comes from `WORKFLOW_UPSTREAM_TIMEOUT_SECONDS`.

Current LCORE A2A artifacts carry answer text only. Results therefore report `evidence_status="unavailable"` unless the upstream response includes structured `referenced_documents` or `rag_chunks` metadata. Inline `<|/documentation/...|>` markers are preserved as text and are not citations. The executor remains a placeholder until the bounded workflow wires this client into the A2A path.

## Development

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run knowledge-agent                    # serves http://127.0.0.1:8081
uv run --env-file .env knowledge-agent    # with local overrides

curl -s http://127.0.0.1:8081/a2a/health
curl -s http://127.0.0.1:8081/.well-known/agent-card.json

uv run pytest -q
uv run ruff check
uv run pyright
```

The service publishes its Agent Card at `/.well-known/agent-card.json` and speaks A2A JSON-RPC `POST /a2a`. The executor remains a placeholder that answers with a fixed text artifact; the LCORE client is implemented and tested, and the bounded workflow will wire it into the executor. Streaming is advertised as unsupported until then.

## Configuration

Copy `.env.example` to `.env` and adjust. Everything comes from the environment; `--host` and `--port` override the bind address. Invalid values fail at startup with an explicit message.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LCORE_AGENT_CARD_URL` | `http://localhost:8080/.well-known/agent-card.json` | LCORE Agent Card used by the upstream client |
| `HOST` / `PORT` | `127.0.0.1` / `8081` | Bind address of this service |
| `PUBLIC_URL` | `http://$HOST:$PORT` | Base URL advertised in the Agent Card |
| `WORKFLOW_MAX_ROUNDS` | `2` | Initial search plus at most one follow-up |
| `WORKFLOW_UPSTREAM_TIMEOUT_SECONDS` | `90` | Per-call timeout for LCORE A2A requests |
| `WORKFLOW_TASK_DEADLINE_SECONDS` | `180` | Whole-task budget |
| `WORKFLOW_MAX_CONCURRENT_TASKS` | `4` | Concurrent task cap |

The per-call timeout is enforced by the LCORE client; the remaining workflow limits will be enforced by the bounded search workflow.
