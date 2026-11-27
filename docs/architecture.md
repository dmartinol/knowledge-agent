# Architecture

## Implementation status

The runtime implements the control-plane design below: a pydantic-ai typed tool
loop with an agent-owned model provider, a retrieval-only LCORE client, and
code-owned rendering of Sources, Gaps, and limitations. The `skills/` tree
supplies the agent instructions and is loaded at startup. Verified citations work
on the REST transport; the A2A structured-evidence envelope is still pending.

## Selected deployment shape

The Knowledge Search agent is a separate A2A service. It accepts A2A requests
from calling agents and uses LCORE as its knowledge service over one configured
transport: LCORE's A2A interface (the code default) or LCORE's REST query
endpoint (selected for provenance documents). The agent owns reasoning. LCORE
owns retrieval execution and the administrator-configured OKP and BYOK sources.

~~~mermaid
sequenceDiagram
    participant Caller as Calling agent
    participant Search as Knowledge Search service
    participant Agent as pydantic-ai agent
    participant LLM as Agent-owned LLM provider
    participant LCORE as LCORE (A2A or REST)
    participant Sources as Configured OKP/BYOK sources

    Caller->>Search: A2A message/send
    Search->>Agent: Question, clarification state, limits
    Agent->>LLM: Typed tool-loop turn
    LLM-->>Agent: Clarify or search_knowledge(query)
    Agent->>LCORE: One retrieval call on the configured transport
    LCORE->>Sources: Retrieve using deployment configuration
    Sources-->>LCORE: Retrieved results
    LCORE-->>Agent: Answer text, plus structured references on REST
    Agent->>LLM: Observation plus remaining budget
    LLM-->>Agent: Search again or final structured answer
    Agent-->>Search: Answer, gaps, evidence state
    Search-->>Caller: A2A artifact with Sources/Gaps/limitations and metadata
~~~

## Control plane and data plane

| Plane | Owner | Responsibilities |
| --- | --- | --- |
| Control | Knowledge Search agent | Clarification, query strategy, follow-up decisions, synthesis, formatting, output validation, workflow limits |
| Data | LCORE | Retrieval execution, administrator-configured source selection, source credentials, answer text and structured references |

The agent's LLM is an agent-owned OpenAI-compatible provider. LCORE is not the
agent's model gateway. LCORE may use its own model internally to produce answer
text; the agent treats that text as untrusted material rather than as a
reasoning service. The agent never sends its decision prompts or consolidation
requests to LCORE.

## Responsibilities

### Knowledge Search service

- Publish an Agent Card describing the knowledge-search skill.
- Maintain A2A task continuity for clarification and final artifacts.
- Run a pydantic-ai typed tool loop with an explicit search tool.
- Enforce clarification, search, model-request, token, deadline, and concurrency
  limits.
- Render Sources, Gaps, and limitations from structured data rather than from
  model-authored citations.

### LCORE

- Execute retrieval using only the OKP and BYOK sources configured by the LCORE
  administrator.
- Return answer text and, when the upstream contract supports it, structured
  document references.
- Keep source credentials, source authorization, and retrieval configuration
  within its deployment.

## A2A contract

The service exposes A2A JSON-RPC to callers. Upstream knowledge work goes to
LCORE over the transport named by `LCORE_RETRIEVER`, chosen once at startup:
`a2a` (default) or `rest`. Requests never carry message metadata, so callers
cannot select a model, provider, vector store, or source scope. The two
transports are never merged within a task, and there is no fallback from one to
the other. LCORE internals are never imported and its databases or model
providers are never contacted directly.

The agent's A2A response uses task states for progress and clarification and a
text artifact for the final answer. The Agent Card still advertises text input
and output and no streaming. The target Agent Card description identifies the
service as an agent-owned reasoning agent backed by an LCORE knowledge service.

### LCORE client

The retrieval adapter has two implementations behind one `search()` surface.

**A2A transport (`LCORE_RETRIEVER=a2a`)**

- Discover `LCORE_AGENT_CARD_URL` once, cache the validated card, and require
  protocol `0.3.x` with JSON-RPC.
- Use non-streaming `message/send` with a text part, blocking completion, one
  attempt, and the configured per-call timeout.
- Send no message metadata. The client API exposes no model, provider,
  vector-store, or source-selection input.
- Start a fresh LCORE context for every search. The workflow does not reuse a
  `contextId`, so material from one search cannot become hidden context for the
  next.
- Normalize completed text, structured references, evidence state, and stable
  error categories. Do not expose LCORE task IDs, tool calls, or raw history to
  the agent model.
- Call the endpoint the card advertises, but treat a loopback or unspecified
  host as a bind address: substitute the scheme, host, and port of
  `LCORE_AGENT_CARD_URL` and keep the advertised path. A peer that publishes
  `localhost` would otherwise fail every search as an unreachable endpoint.

**REST transport (`LCORE_RETRIEVER=rest`)**

- Send `POST <LCORE_REST_URL>/v1/query` with exactly `{"query": ...}`. No
  authorization header, conversation ID, or optional model, provider,
  vector-store, and source fields. This path is unauthenticated for the POC.
- Map `referenced_documents` to the evidence contract as
  `source`, `document_id`, `title`, `url`, and `support=retrieved`. Ignore
  `rag_chunks`, `tool_calls`, `tool_results`, and token counters.
- Deduplicate references and report `evidence_status=available` only when at
  least one traceable document remains; an empty or unusable list reports
  `none`, which produces the unverified limitation.
- Apply the same per-call timeout, material truncation, and stable error
  categories as A2A. Upstream `truncated` is propagated and local truncation is
  marked. REST returns no task or context IDs.

## Agent reasoning loop

The agent uses pydantic-ai with an OpenAI-compatible model provider and a typed
tool loop. The shape is a bounded ReAct cycle: one tool, code-enforced bounds,
and no stored reasoning step. `workflow-loop.md` maps each part of it to the
code:

- `search_knowledge(query)` performs one LCORE A2A search and returns an
  observation containing answer text, evidence status, structured references,
  the search index, and whether the search limit was reached.
- The model may ask one clarification, search, search once more when the first
  observation leaves a concrete gap, or finish with a structured answer.
- The final output is a discriminated union of `ClarificationRequest` and
  `KnowledgeAnswer`. `KnowledgeAnswer` contains only the answer text and a list
  of gaps. Code rejects model-authored Sources, References, or Gaps sections,
  URLs, empty answers, and answers produced before any search.
- Code appends Sources from the deduplicated union of structured references
  across searches, renders Gaps from the structured field, and adds limit
  limitations.
- Deployment configuration may supply an internal and a public base for Source
  URLs. When both are set, the rendered artifact rebases URLs that start with
  the internal base onto the public one and keeps LCORE's value as
  `upstream_url`; the references the model sees are untouched.

Agent instructions are composed at startup from two sources. Code owns a short
block of invariants: the agent serves A2A callers, LCORE is retrieval-only and its
deployment configuration selects sources, `search_knowledge` is the only tool,
tool output is data, and the service renders citations and gaps. The `skills/`
tree owns the rest: `knowledge-search` (clarification, query strategy, follow-up)
and `answer-synthesis` (evidence use, answer shape, gap reporting).

`pydantic-ai-harness[skills]` parses and validates the `SKILL.md` packages, then
each skill is rendered into the model instructions before the run starts. Skills
are not exposed as deferred capabilities: both apply to every task, so loading
them through the model would spend requests from the per-task budget. `Skills`
also ignores unknown frontmatter such as `version`, which the runtime reads
separately for the startup log. Bounds, validation, retries, and evidence
rendering remain code-only and cannot be changed by skill text.

## Evidence and output contract

LCORE answer text is untrusted material. The agent must treat it as data, never
as instructions, and must not add facts outside it. Inline
`<|/documentation/...|>` markers are never citations.

Only structured references count as evidence. The target LCORE evidence
envelope is the `referenced_documents` list or an equivalent artifact-metadata
envelope with stable document identity, title, URL, and a `support` marker.
Only references marked as retrieved become Sources. If LCORE returns no
structured references, the answer is labeled unverified and the limitation is
stated explicitly. The agent must not infer citations from prose.

The user-facing artifact contains, in order:

1. The model's answer.
2. A code-rendered `Gaps:` section, when the model reports gaps or a search limit
   was reached.
3. A code-rendered `Sources:` section from structured references, or an explicit
   unverified limitation when none exist.

Artifact metadata under `knowledge_agent` records the observable workflow state:

| Field | Meaning |
| --- | --- |
| `loop` | `typed_tool` |
| `decision_source` | `llm` |
| `searches` / `search_limit` | LCORE searches performed and the hard cap |
| `evidence_status` | `available`, `none`, `unavailable`, or `not_configured` |
| `evidence` | Structured references with their search index |
| `gaps` | Code-owned gap list, including the search-limit gap |
| `limitation` | The unverified limitation, or `null` when references exist |
| `llm_requests` / `llm_tokens` | Agent model usage, when reported by the provider |
| `clarification_used` | Whether the task consumed its one clarification |
| `limits_hit` | Search, model-request, token, or deadline limits that fired |
| `error` | Stable failure category for failed tasks |

The metadata never contains prompts, raw LCORE material, model messages, or
chain-of-thought.

## Bounds and failure modes

| Bound | Target default | Enforced by |
| --- | --- | --- |
| LCORE searches | 2 | `WORKFLOW_MAX_ROUNDS` and the search tool |
| Agent model requests | 6 | pydantic-ai `UsageLimits` |
| Agent tokens | 60,000 | pydantic-ai `UsageLimits` |
| Agent model call | 60 s | Model-provider timeout |
| LCORE call | 90 s | LCORE client |
| LCORE material per search | 12,000 chars | `WORKFLOW_MAX_MATERIAL_CHARS` |
| Whole task | 180 s | `asyncio.timeout` |
| Concurrent tasks | 4 | Semaphore |
| Clarifications | 1 | Executor and task metadata |

- A missing model, model timeout, malformed final output, or exhausted
  model-request or token limit fails the task with a stable error. There is no
  deterministic answer fallback.
- An LCORE error fails the task with the existing stable upstream error
  categories.
- Reaching the search cap is not a failure. The model must answer from available
  material and code appends a search-limit gap.
- A deadline before a final answer fails the task. No partial answer is
  presented as a completed one.
- Concurrency exhaustion rejects the task before work starts.

## Configuration

The agent model is configured through `AGENT_LLM_BASE_URL`,
`AGENT_LLM_MODEL`, `AGENT_LLM_API_KEY`, `AGENT_LLM_TIMEOUT_SECONDS`,
`AGENT_LLM_REQUEST_LIMIT`, and `AGENT_LLM_TOTAL_TOKENS_LIMIT`. Local runs may
fall back to `OPENAI_BASE_URL`, `E2E_OPENAI_MODEL`, and
`OPENAI_API_KEY`. All three model values must resolve together;
the service exits at startup when they do not. The LCORE URL and workflow limits
keep their existing configuration names, and
`WORKFLOW_MAX_MATERIAL_CHARS` bounds the material handed to the model.
`WORKFLOW_FOLLOW_UP_POLICY` is retired because the model, not a rules policy,
decides follow-ups.

## Known constraints

- The current LCORE A2A handler is a general query path, not a dedicated
  retrieval API.
- The current LCORE A2A response is text-oriented. Structured references are
  forward-compatible but not yet available in the deployed contract.
- LCORE's current A2A path does not use standard LCORE quota accounting, and the
  agent's model provider may not report token usage. Local limits remain
  mandatory.
- A typed tool loop requires a model that supports OpenAI-compatible tool calls
  and structured output.
- LCORE material can contain untrusted instructions. Prompt-injection handling
  and provider data-retention policy remain open questions.

See [the workflow loop](workflow-loop.md) for the exact loop contract and
[open questions](open-questions.md) for unresolved upstream and deployment
details.
