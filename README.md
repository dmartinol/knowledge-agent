# Knowledge Search Agent

A proof of concept for an A2A knowledge-search agent with agent-owned reasoning
and an LCORE knowledge service. The agent decides when to clarify, what to
search, whether a second search is justified, and how to synthesize the answer.
LCORE executes retrieval against administrator-configured OKP and BYOK sources.

## Implementation status

The runtime implements the pydantic-ai typed tool loop described here: the model
decides clarification, searches, and follow-ups, while LCORE is retrieval-only.
Two pieces of the target foundation are still pending: the `skills/` tree is
authored but not yet loaded into the agent, and verified citations depend on the
upstream structured evidence envelope.

## Architecture

This repository owns the Knowledge Search agent and its A2A interface.

- The agent owns the control plane: clarification, query strategy, follow-up,
  synthesis, formatting, and workflow limits.
- LCORE owns the data plane: retrieval execution and the administrator-configured
  OKP and BYOK sources and credentials.
- The agent uses an agent-owned OpenAI-compatible model provider through
  pydantic-ai. LCORE is not the agent's model gateway and is never asked to make
  control-plane decisions or consolidate answers.
- Callers cannot select vector stores, LCORE models, or source scopes. The LCORE
  client sends no message metadata, and the search tool accepts only a query.
- Upstream LCORE traffic uses A2A JSON-RPC. The agent does not use LCORE REST
  query endpoints, import LCORE internals, or connect to its vector databases.

See [the architecture notes](docs/architecture.md),
[the workflow loop](docs/workflow-loop.md), and
[open questions](docs/open-questions.md) before implementing the runtime.

## Upstream contract

[The LCORE A2A contract report](docs/lcore-a2a-contract.md) records what the
local LCORE deployment actually returns: retrieval runs, but the A2A artifact
carries only the final answer text and `conversation_id`. REST exposes chunks and
referenced documents, but the agent does not use REST. The missing A2A evidence
contract remains an open upstream gap.

Consequences for this agent: LCORE text is untrusted material for synthesis, not
a citation contract. Only structured references can become Sources. If LCORE
returns none, the answer is labeled unverified. Inline
`<|/documentation/...|>` markers are never citations.

## Agent loop

The target workflow uses pydantic-ai with an OpenAI-compatible model provider and
a typed tool loop:

- `search_knowledge(query)` performs one LCORE A2A search.
- The model may ask one clarification, search, search once more when the first
  observation leaves a concrete gap, or finish with a structured answer.
- Code enforces the two-search cap, one-clarification limit, model-request and
  token limits, task deadline, and concurrency.
- The model returns an answer and structured gaps only. Code renders Sources,
  Gaps, and limitations from structured data.
- There is no LCORE consolidation call and no deterministic answer fallback. If
  the reasoning model is unavailable or returns unusable output, the task fails
  with a stable error.

Agent instructions currently live in `knowledge_agent.reasoning.SYSTEM_PROMPT`.
The `skills/` tree already holds `knowledge-search` (clarification and search
strategy) and `answer-synthesis` (evidence use, answer shape, gap reporting);
loading them through the `Skills` capability of `pydantic-ai-harness` is the next
step.

## LCORE client

`knowledge_agent.lcore_client.LcoreClient` discovers the Agent Card at
`LCORE_AGENT_CARD_URL`, caches it, and sends one non-streaming `message/send` per
`search()` call. Requests carry no message metadata, so callers cannot select a
model, provider, or vector store. Each search uses a fresh LCORE context; the
workflow never reuses a `contextId`. Failures are normalized to `LcoreError`
categories, and the per-call timeout comes from
`WORKFLOW_UPSTREAM_TIMEOUT_SECONDS`.

Current LCORE A2A artifacts carry answer text only. Results therefore report
`evidence_status="unavailable"` unless the upstream response includes structured
references: the `evidence{schema_version,status,retrieved_by,documents[]}`
envelope, or the legacy `referenced_documents`/`rag_chunks` fallback. Only
documents marked `support=retrieved` become Sources. Material handed to the
model is truncated to `WORKFLOW_MAX_MATERIAL_CHARS`, and inline
`<|/documentation/...|>` markers are never citations.

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

The service publishes its Agent Card at `/.well-known/agent-card.json` and speaks
A2A JSON-RPC `POST /a2a`. Streaming is advertised as unsupported; the workflow
answers with a single text artifact plus workflow metadata.

## Configuration

Copy `.env.example` to `.env` and adjust. Everything comes from the environment;
`--host` and `--port` override the bind address. Invalid values fail at startup
with an explicit message.

| Variable | Default | Purpose |
| --- | --- | --- |
| `LCORE_AGENT_CARD_URL` | `http://localhost:8080/.well-known/agent-card.json` | LCORE Agent Card used by the upstream client |
| `HOST` / `PORT` | `127.0.0.1` / `8081` | Bind address of this service |
| `PUBLIC_URL` | `http://$HOST:$PORT` | Base URL advertised in the Agent Card |
| `AGENT_LLM_BASE_URL` | fallback to `OPENAI_BASE_URL` | OpenAI-compatible agent model endpoint |
| `AGENT_LLM_MODEL` | fallback to `E2E_OPENAI_MODEL` | Agent reasoning model |
| `AGENT_LLM_API_KEY` | fallback to `ENMAAS_KEY` or `OPENAI_API_KEY` | Agent model credential |
| `AGENT_LLM_TIMEOUT_SECONDS` | `60` | Per-request agent model timeout |
| `AGENT_LLM_REQUEST_LIMIT` | `6` | Maximum model requests per task |
| `AGENT_LLM_TOTAL_TOKENS_LIMIT` | `60000` | Maximum agent model tokens per task |
| `WORKFLOW_MAX_ROUNDS` | `2` | Maximum LCORE searches: `1` disables the follow-up |
| `WORKFLOW_MAX_MATERIAL_CHARS` | `12000` | Maximum LCORE characters given to the model per search |
| `WORKFLOW_UPSTREAM_TIMEOUT_SECONDS` | `90` | Per-call timeout for LCORE A2A requests |
| `WORKFLOW_TASK_DEADLINE_SECONDS` | `180` | Whole-task budget |
| `WORKFLOW_MAX_CONCURRENT_TASKS` | `4` | Concurrent task cap |

The three `AGENT_LLM_*` model values must be set together; the service refuses to
start without them. `WORKFLOW_MAX_ROUNDS` is the hard search cap because the
model decides follow-ups. The LCORE defaults stay at 90 s and 180 s because the
local contract report measured RAG answers taking up to 70 s over A2A; the MVP's
30 s / 60 s figures would cut off real answers.

## Out of scope

- Hidden chain-of-thought or free-form planning output.
- LCORE token or cost accounting.
- LCORE conversation reuse or LCORE-side consolidation.
- Task cancellation in flight.
- Persistence across process restarts; task and clarification state are in
  memory for the POC.
