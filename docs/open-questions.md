# Open Questions

Resolve these against the deployed LCORE version and the selected agent model
before depending on them. Status words are `Verified`, `Decided`, and `Open`.

## 1. Evidence returned over A2A

- Verified: the LCORE Agent Card describes a generic text query skill and no
  retrieval metadata.
- Verified: A2A artifacts currently contain answer text and `conversation_id`;
  the REST query path exposes chunks and referenced documents, but the agent does
  not use REST.
- Decided: LCORE answer text is treated as untrusted material, not as a citation
  contract. Only structured references become Sources.
- Open: the final A2A evidence envelope for stable document IDs, titles, URLs,
  and support markers. The target shape is the `referenced_documents` list or an
  artifact-level evidence object with retrieved-versus-cited support.
- Open: how long the deployed LCORE version will remain text-only over A2A, and
  whether the evidence envelope is versioned.
- Interim behavior: answers without structured references are labeled unverified.

## 2. Source selection and caller metadata

- Verified: retrieval uses the sources configured in LCORE deployment
  configuration.
- Verified: LCORE accepts `model`, `provider`, and `vector_store_ids` in message
  metadata, so server-side configuration is authoritative only if the client
  never sends those fields.
- Decided: the LCORE client sends no message metadata and the search tool accepts
  only a query string.
- Open: confirm how LCORE handles metadata if another client sends it, and keep
  server-side configuration authoritative.

## 3. Agent-owned reasoning and model provider

- Decided: the agent uses pydantic-ai with an OpenAI-compatible provider owned by
  the agent, not LCORE.
- Decided: the model drives clarification, search strategy, follow-up, and final
  synthesis through a typed tool loop. LCORE is not used for control-plane
  decisions or consolidation.
- Open: validate that the selected model supports OpenAI-compatible tool calls
  and structured output. If it does not, the typed tool loop cannot run.
- Open: the exact production model, provider, data-retention terms, and regional
  routing.
- Open: whether provider-reported token usage is available for the configured
  endpoint. Without usage, only request-count and deadline limits are exact.

## 4. Agent skills and prompt assets

- Decided: instructions live in the agent's `skills/` tree and are loaded with
  the `Skills` capability of `pydantic-ai-harness[skills]`. LCORE skills are out
  of scope.
- Decided: skills activation is deferred. The current runtime carries the same
  guidance in a code-owned system prompt, and artifact metadata reports an empty
  skill list until the capability is wired in.
- Open: pin a compatible pydantic-ai and `pydantic-ai-harness` version pair and
  verify progressive disclosure behavior in the service.
- Open: skill ownership, review, and versioning. Artifact metadata should record
  the skill names and versions used for a run.
- Open: prompt-injection resistance for LCORE material. The current design wraps
  material as data and instructs the model to ignore embedded instructions; this
  needs adversarial tests.

## 5. Quota and operational limits

- Verified: the LCORE A2A path reports no token usage, quota, or cost data.
- Decided: code enforces LCORE search count, model-request count, total tokens,
  per-call timeouts, task deadline, and concurrency.
- Open: operator reporting for limit exhaustion beyond artifact metadata and
  structured logs.
- Open: whether model cost limits are meaningful for the selected provider and
  model pricing.

## 6. Clarification and task continuity

- Verified: LCORE never returns `input-required`; clarification is entirely
  agent-owned.
- Decided: one clarification per task. The pending question is stored in A2A task
  metadata, and the caller resumes with the same `taskId`. The resumed run cannot
  ask a second clarification.
- Decided: LCORE context IDs are not reused across searches.
- Open: mapping caller context to persisted agent state across process restarts,
  plus cleanup and expiry behavior.

## 7. Authentication and deployment

- Verified locally: LCORE A2A requires no credentials with `auth_enabled: false`
  and the `noop` authentication module.
- Decided: the agent model credentials come from deployment-managed secret
  configuration and are never exposed to callers.
- Open: the production service identity, caller identity delegation, and whether
  the A2A endpoint requires authentication outside the POC.
- Open: network policy and egress requirements for the agent-to-model-provider
  connection.

## 8. Failure behavior

- Decided: model unavailability, model timeout, malformed final output, and
  exhausted model limits fail the task. There is no deterministic answer
  fallback.
- Open: whether a failed task should be retryable by the caller with the same
  task ID or require a new task.
