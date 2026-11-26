# Workflow Loop

## Status

This document specifies the agent-owned reasoning loop, and the runtime
implements it. Two parts remain open: the skills below are authored but still
delivered through the runtime system prompt, and verified citations depend on
the upstream structured evidence envelope.

## Principles

- The agent owns the control plane. The model decides when to clarify, what to
  search, whether a second search is justified, and when to answer.
- LCORE is the data plane. One search tool call is one LCORE A2A
  `message/send`; no LCORE call is made for clarification, follow-up policy,
  consolidation, or formatting.
- Code owns the hard bounds. The model cannot widen the search count, model
  request count, token budget, deadline, concurrency, or clarification count.
- Code owns evidence rendering. The model writes the answer and gaps; Sources,
  limitations, and metadata come from structured data.
- No hidden chain-of-thought, raw model messages, or free-form planning is
  returned to callers or logged.

## Components

| Component | Responsibility |
| --- | --- |
| A2A executor | Validates the caller message, manages task state, enforces the task deadline and concurrency slot, and maps results to A2A states |
| pydantic-ai agent | Runs the typed tool loop with the agent-owned model provider |
| `search_knowledge` tool | Performs one fresh LCORE A2A search and returns a bounded observation |
| `skills/` tree | Holds the agent instructions for search strategy and answer synthesis; the target loader is `pydantic-ai-harness[skills]` `Skills` |
| Result renderer | Appends code-owned Sources, Gaps, and limitations and emits artifact metadata |

## Request lifecycle

1. The executor validates the caller's text and reads any pending clarification
   state from task metadata.
   An empty message without a pending clarification completes with a short
   request for a concrete question, without a model or LCORE call.
2. If a clarification is pending, the executor composes the original question
   with the caller's reply, marks the clarification as used, and runs the agent
   with an answer-only output contract.
3. Otherwise the executor gives the agent the caller's question and a
   clarification-available output contract.
4. The model either emits `ClarificationRequest` or calls
   `search_knowledge(query)`.
5. Each search returns an observation. The model may call the tool again once,
   or finish with `KnowledgeAnswer`.
6. The executor validates the structured answer, renders the final text from the
   answer plus code-owned sections, emits one artifact, and completes the task.

## Structured output

The model's final output is a discriminated union:

| Type | Fields | Validity |
| --- | --- | --- |
| `ClarificationRequest` | `question` | Only before the first search and only when the task has not used its clarification |
| `KnowledgeAnswer` | `answer`, `gaps[]` | Only after at least one search |

Rules enforced by code:

- `answer` is non-empty.
- `gaps` is a list of short strings; the renderer owns the `Gaps:` heading.
- The answer must not contain a Sources, References, or Citations section, a
  Gaps heading, or URLs. Citations are code-owned.
- An answer before any search is rejected with a model retry.
- A clarification after a search or after the one allowed clarification is
  rejected with a model retry. Repeated violations fail the task.
- pydantic-ai output-validation retries are allowed within the model-request
  limit. There is no deterministic answer fallback.

## Search tool contract

The only tool that reaches LCORE is:

```text
search_knowledge(query: str) -> SearchObservation
```

It accepts no source, model, provider, vector-store, or context parameter. The
query is the model's search text; LCORE deployment configuration remains the
authority for what is retrieved.

`SearchObservation` contains:

| Field | Meaning |
| --- | --- |
| `query` | The normalized query sent to LCORE |
| `text` | LCORE answer text, bounded to the configured material limit |
| `evidence_status` | `available`, `none`, or `unavailable` |
| `references` | Structured references with title, URL, document identity, and support marker |
| `search_index` | 1-based search number |
| `truncated` | Whether the material was truncated for the model context |
| `limit_reached` | True when a further call would exceed `WORKFLOW_MAX_ROUNDS` |

The tool does not expose LCORE task IDs, context IDs, tool calls, raw history,
or upstream metadata. An LCORE error fails the task; it is not converted into a
model observation. The tool never reuses an LCORE `contextId`: every search
starts a fresh LCORE conversation.

## Clarification

Clarification is agent-owned and happens before the loop enters its search
phase. At most one clarification is asked per A2A task.

- The first model call may return `ClarificationRequest` when the request is
  empty, a greeting, a pronoun-only fragment, or otherwise too underspecified to
  search.
- The executor stores the original question and phase under task metadata,
  returns `input-required`, and makes no LCORE call.
- The caller resumes by sending another message with the same `taskId`.
- The resumed run composes the original question with the caller's reply and
  uses an answer-only output contract. A second clarification is impossible; the
  model must search and answer or fail.
- An empty resumed reply completes with a short request for a concrete question,
  without starting the model loop.

## Search strategy

The model decides the first query. It should use the caller's own terminology
and preserve the requested product, version, or scope. It should not invent a
source, model, or vector store.

A second search is allowed only when the first observation leaves a concrete
coverage gap or a materially better query is available. The model must not
search again merely to restate the question. The second query is self-contained:
it includes the original question and the specific gap or alternate terminology,
because LCORE context is not reused.

At most two LCORE searches run. When the cap is reached, the tool returns
`limit_reached` instead of calling LCORE. The model must then answer from the
material it has, and the renderer adds a search-limit gap.

## Evidence and answer rendering

LCORE answer text is untrusted material. The agent instructions wrap the material
as data, tell the model to ignore instructions inside it, and forbid facts that
the material does not support. The model may organize and explain the material;
it may not invent citations, sources, or coverage.

Only structured references become Sources. The renderer:

1. Unions references across searches in search order and deduplicates them on
   stable document identity.
2. Accepts only references marked as retrieved. Model-cited references are not
   treated as verified evidence.
3. Renders `Sources:` from the union, or an explicit unverified limitation when
   no structured references exist.
4. Renders `Gaps:` from the structured gaps field and adds a search-limit gap
   when the cap was reached.
5. Strips inline `<|...|>` markers and a leading `Answer:` label from the model
   answer. There is no narration heuristic: the system prompt and the output
   validator own the answer shape.

Inline `<|/documentation/...|>` markers are never rendered as citations. If they
appear in the model answer, the renderer strips them before display.

## Bounds

| Bound | Setting | Enforced by |
| --- | --- | --- |
| LCORE searches | `WORKFLOW_MAX_ROUNDS` (1 or 2) | Search tool and loop state |
| Model requests | `AGENT_LLM_REQUEST_LIMIT` (default 6) | pydantic-ai `UsageLimits` |
| Model tokens | `AGENT_LLM_TOTAL_TOKENS_LIMIT` (default 60,000) | pydantic-ai `UsageLimits` |
| Model call | `AGENT_LLM_TIMEOUT_SECONDS` (default 60) | Provider client timeout |
| LCORE call | `WORKFLOW_UPSTREAM_TIMEOUT_SECONDS` (default 90) | LCORE client |
| LCORE material | `WORKFLOW_MAX_MATERIAL_CHARS` (default 12,000) | LCORE client |
| Whole task | `WORKFLOW_TASK_DEADLINE_SECONDS` (default 180) | `asyncio.timeout` |
| Concurrent tasks | `WORKFLOW_MAX_CONCURRENT_TASKS` (default 4) | Semaphore |
| Clarifications | 1 | Executor and task metadata |

`WORKFLOW_FOLLOW_UP_POLICY` is retired. The model makes the follow-up decision;
`WORKFLOW_MAX_ROUNDS` is the only search-count control.

## Termination and failure

| Condition | Task outcome |
| --- | --- |
| Model returns `ClarificationRequest` on the first turn | `input-required`, no LCORE call |
| Model returns `KnowledgeAnswer` after one or two searches | `completed` with rendered answer |
| Search cap reached | Model must answer; renderer adds the search-limit gap |
| Model returns malformed or empty final output | `failed` with a stable model-output error |
| Model provider unavailable or times out | `failed` with a stable model-unavailable error |
| Model-request or token limit exhausted before an answer | `failed` with a stable limit error |
| Task deadline before a final answer | `failed` with a deadline error |
| LCORE search fails | `failed` with the existing upstream error category |
| Concurrency slot unavailable | `rejected` |

Failed tasks contain only a stable error category. They never contain the query,
LCORE material, model messages, or a deterministic substitute answer.

## Artifact metadata

The successful artifact metadata under `knowledge_agent` is:

```json
{
  "loop": "typed_tool",
  "decision_source": "llm",
  "searches": 2,
  "search_limit": 2,
  "evidence_status": "unavailable",
  "evidence": [],
  "llm_requests": 4,
  "llm_tokens": 12345,
  "clarification_used": false,
  "skills": [],
  "limits_hit": []
}
```

`evidence[]` entries carry the same stable reference identity used for
deduplication plus their 1-based `search` index. `limits_hit` can contain
`search`, `model_requests`, `tokens`, or `deadline`. Failed tasks replace the
success fields with `{"error": "<stable_category>", "limits_hit": [...]}`.
Failure categories are `model_config_error`, `model_unavailable`,
`model_timeout`, `model_limit`, `model_output_invalid`, `deadline`, and the
existing LCORE categories. `skills` stays empty until the `Skills` capability is
wired in.

## Logging and privacy

Log only counts, statuses, skill names, limit names, latency, and stable error
categories. Do not log caller text, LCORE material, prompts, model messages,
authorization headers, or full references. Provider usage is recorded only when
the provider reports it.

## Testing expectations

The implementation must cover:

- Clarification on the first turn, resume with the same task, and rejection of a
  second clarification.
- Search-tool contract, caller metadata rejection, fresh LCORE context, two-search
  cap, and search-limit gap.
- Valid structured answers, malformed output, empty output, URLs or
  model-authored Sources, and answer-before-search rejection.
- Model unavailable, model timeout, model-request limit, token limit, task
  deadline, LCORE error, and concurrency rejection.
- Evidence union, deduplication, unverified labeling, prompt-injection material,
  and inline-marker stripping.

## Out of scope

- Hidden chain-of-thought or free-form planning output.
- LCORE token or cost accounting.
- LCORE conversation reuse or LCORE-side consolidation.
- Task cancellation in flight.
- Persistence across process restarts; task and clarification state remain in
  memory for the POC.
