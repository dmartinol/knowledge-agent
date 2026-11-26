# Architecture

## Selected deployment shape

The Knowledge Search agent is a separate service. It accepts A2A requests from calling agents and uses LCORE as its upstream service through A2A. LCORE remains the owner of model serving and administrator-configured OKP/BYOK retrieval.

~~~mermaid
sequenceDiagram
    participant Caller as Calling agent
    participant Search as Knowledge Search service
    participant LCORE as LCORE A2A service
    participant Sources as Configured OKP/BYOK sources

    Caller->>Search: A2A message/send or message/stream
    Search->>Search: Validate, plan, and bound the workflow
    Search->>LCORE: A2A query
    LCORE->>Sources: Retrieve using deployment configuration
    Sources-->>LCORE: Retrieved results
    LCORE-->>Search: A2A task and artifact
    Search->>Search: Assess evidence and decide answer, clarify, or retry
    Search-->>Caller: A2A task, answer, citations, or evidence gap
~~~

## Responsibilities

### Knowledge Search service

- Publish an Agent Card describing the knowledge-search skill.
- Maintain A2A task and context continuity for its callers.
- Apply the bounded workflow: clarify when needed, submit a query, assess the returned evidence, optionally retry, and synthesize the outcome.
- Present citations or explain evidence gaps based only on upstream evidence.

### LCORE

- Resolve the model and execute retrieval.
- Use only OKP and BYOK sources configured by the LCORE administrator.
- Keep source credentials and source authorization within its deployment.

## A2A contract

The service uses the LCORE Agent Card and A2A JSON-RPC endpoint for upstream query work. It does not send vector-store IDs in message metadata. It should propagate only authentication information explicitly supported by the LCORE deployment.

The agent's A2A response can use task states for progress and clarification, and artifacts for the final answer and evidence. The exact artifact shape depends on what the deployed LCORE A2A interface returns and what the calling agents need.

### LCORE client

- Discover `LCORE_AGENT_CARD_URL` once, cache the validated card, and require protocol `0.3.x` with JSON-RPC.
- Use non-streaming `message/send` with a text part, blocking completion, one attempt, and the configured per-call timeout.
- Send no message metadata. The client API exposes no model, provider, vector-store, or source-selection input.
- Normalize completed text, task and context IDs, structured evidence, and stable error categories.
- Treat evidence as unavailable unless LCORE supplies `referenced_documents` or `rag_chunks` in artifact metadata or data parts. Do not infer citations from prose.

## Controlled workflow

1. Validate the caller's request and ask one clarification question when it is empty, a pronoun-only fragment, or a greeting.
2. Send the composed question to LCORE, then assess the observation: `evidence_status` plus the normalized evidence.
3. Run at most one follow-up, selected by `WORKFLOW_FOLLOW_UP_POLICY`:

| Policy | Follow-up when |
| --- | --- |
| `evidence` | LCORE returns an explicit empty evidence set |
| `auto` | Evidence decides when present; a conservative answer-text heuristic applies only when evidence is unavailable |
| `heuristic` | The answer is empty, very short, or contains a fixed "no answer" phrase |
| `never` | Never |

4. Stop at the round, per-call, task-deadline, and concurrency limits, and say when a gap remains.
5. Consolidate: when there is more than one search result, send one fixed-template request to the same LCORE A2A endpoint over the existing `contextId` and use its reply as the answer body; otherwise use the last answer. Always append sources from the deduplicated union of structured evidence across searches, never from the consolidation reply. Relay the answer with an explicit unverified label when no structured evidence exists.

The consolidation template is fixed and versioned in `src/knowledge_agent/consolidation.py`; it adds no second model provider and no second retrieval path. If the request fails, times out, or returns blank text, the workflow falls back to the last answer with a documented set of leading narration prefixes removed, and records `consolidation: fallback`. Per-search provenance stays in artifact metadata as `evidence.search`, not in the user-facing answer.

Clarification uses the A2A `input-required` state. The workflow stores the pending question in task metadata and resumes when the caller sends another message for the same task. Follow-up searches reuse LCORE's `contextId`. The executor exposes counts, evidence status, and the follow-up decision, but not hidden reasoning.

The loop and its termination rules are specified in [the workflow loop](workflow-loop.md).

## Known constraints

- The current LCORE A2A handler is a general query path, not a dedicated raw-retrieval API.
- The current LCORE A2A response is text-oriented. The client reports evidence as unavailable; structured evidence handling is forward-compatible but unverified upstream.
- LCORE's current A2A path does not use standard LCORE quota accounting. Local limits are required until the upstream policy is clarified.
- LCORE currently accepts vector-store IDs in request metadata. The client sends no metadata, and server-side configuration remains authoritative.
- The `auto` and `heuristic` follow-up policies infer a possible gap from answer text. That is a documented deviation from strict evidence-driven behavior, used only until LCORE returns structured evidence over A2A.

See [open questions](open-questions.md) for the validation checklist.
