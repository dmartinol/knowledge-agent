# Open Questions

Resolve these against the LCORE version used by the POC before depending on them.

## 1. Evidence returned over A2A

- Does the LCORE Agent Card describe the query skill and its supported inputs?
- Does an A2A task artifact include source names, document IDs, URLs, excerpts, or scores?
- Are those references stable and sufficient for the Knowledge Search service to cite?
- If LCORE returns only generated text, what supported interface can provide evidence without bypassing the service boundary?

## 2. Source selection

- Confirm the deployed LCORE configuration selects the intended OKP and BYOK sources.
- Confirm how the current vector_store_ids metadata is ignored or rejected for this service.
- Keep the agent's upstream calls independent of source IDs.

## 3. Authentication and caller context

- Determine how the agent authenticates to LCORE A2A.
- Determine whether caller identity must be delegated to LCORE or whether the service uses a service identity.
- Forward only documented headers and credentials.

## 4. Quota and operational limits

- LCORE's current A2A path does not apply standard quota accounting.
- Decide which service-level limits are required for calls, retries, concurrency, time, and model usage.
- Establish how limits and usage will be reported to operators.

## 5. Clarification and task continuity

- Confirm how the calling A2A client resumes a task after an input-required status.
- Decide how context IDs map to the agent's search state and upstream LCORE context.
- Define cleanup and expiry behavior for persisted contexts.
