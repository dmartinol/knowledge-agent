# Open Questions

Resolve these against the LCORE version used by the POC before depending on them.

## 1. Evidence returned over A2A

- Verified: the LCORE Agent Card describes a generic text query skill and no retrieval metadata.
- Verified: A2A artifacts currently contain only answer text and `conversation_id`; REST exposes `rag_chunks` and `referenced_documents`.
- Open: the upstream contract for returning structured evidence over A2A, including stable document IDs, URLs, excerpts, and scores.
- Current behavior: the agent treats prose and inline documentation markers as unverified text, not citations.

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
- Configured: a per-call timeout is enforced by the LCORE client; workflow round, concurrency, and task-deadline limits will be enforced by the bounded workflow.
- Open: operator reporting for usage and limit exhaustion.

## 5. Clarification and task continuity

- Verified: LCORE never returns `input-required`; clarification is entirely agent-owned.
- Verified: reusing `contextId` continues an LCORE conversation.
- Open: mapping caller context to persisted agent state, plus cleanup and expiry behavior.
