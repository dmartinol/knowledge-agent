# Open Questions

Resolve these against the LCORE version used by the POC before depending on them.

## 1. Evidence returned over A2A

- Verified: the LCORE Agent Card describes a generic text query skill and no retrieval metadata.
- Verified: A2A artifacts currently contain only answer text and `conversation_id`; REST exposes `rag_chunks` and `referenced_documents`.
- Open: the upstream contract for returning structured evidence over A2A, including stable document IDs, URLs, excerpts, and scores.
- Current behavior: the agent treats prose and inline documentation markers as unverified text, not citations.
- Interim deviation: the `auto` and `heuristic` follow-up policies use a fixed answer-text heuristic when evidence is unavailable, and must be revisited once the evidence contract is resolved.
- Verified: LCORE answer text can include process narration such as "I broadened the search" on follow-up turns. The consolidation template forbids it, and a fixed prefix list removes it from both the template reply and the deterministic fallback. A structured "answer + rationale" split upstream would make that guard unnecessary.
- Open: whether the consolidation request should keep reusing LCORE's conversation or become a dedicated upstream skill with an explicit "answer + gap" schema. Until then the template in `src/knowledge_agent/consolidation.py` is the contract.

## 2. Source selection

- Verified locally: retrieval uses the sources configured in LCORE deployment configuration.
- Enforced client-side: `LcoreClient` sends no message metadata, so callers cannot supply `model`, `provider`, or `vector_store_ids`.
- Open: confirm how LCORE handles metadata if another client sends it, and keep server-side configuration authoritative.

## 3. Authentication and caller context

- Verified locally: LCORE A2A requires no credentials with `auth_enabled: false` and the `noop` authentication module.
- Open: the production service identity and whether caller identity must be delegated.
- Rule: forward only documented headers and credentials.

## 4. Quota and operational limits

- Verified: the A2A path reports no token usage, quota, or cost data.
- Configured: the LCORE client enforces the per-call timeout; the executor enforces round, concurrency, and task-deadline limits. Defaults are 90 s per call and 180 s per task because RAG answers were measured at up to 70 s over A2A; the MVP's 30 s / 60 s figures are documented as too low for this deployment.
- Open: operator reporting for usage and limit exhaustion.

## 5. Clarification and task continuity

- Verified: LCORE never returns `input-required`; clarification is entirely agent-owned.
- Verified: reusing `contextId` continues an LCORE conversation.
- Implemented: one clarification per task, with the pending question stored in A2A task metadata; the caller resumes by sending a message with the same `taskId`.
- Open: mapping caller context to persisted agent state across process restarts, plus cleanup and expiry behavior.
