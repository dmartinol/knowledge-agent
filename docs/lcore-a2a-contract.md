# LCORE local A2A contract — verification report

Verification for the evidence-aware knowledge-search design. Everything below was captured
against a running LCORE instance on `http://localhost:8080`, configured by
`lightspeed-stack.yaml` from the `lightspeed-stack` checkout; the exact file and a
redacted `.env` are kept in `docs/lcore-a2a-contract/`. Raw payload excerpts are
quoted as received.

## 1. Instance under test

| Property | Value |
| --- | --- |
| Endpoint | `http://localhost:8080` |
| LCORE version | `0.8.0rc1` |
| A2A SDK version | `0.3.4` |
| Advertised protocol version | `0.3.0` |
| Transport | `JSONRPC` |
| Auth | `service.auth_enabled: false`, `authentication.module: noop` |
| Model reported in task metadata | `openai/rits/zai-org/glm-5-3` |
| Retrieval configuration | `rag.retrieval.tool.sources: [okp]`, `max_chunks: 1`, OKP `search_mode: keyword` |

`GET /a2a/health` returns the version fields above:

```json
{"status":"healthy","service":"lightspeed-a2a","version":"0.8.0rc1","a2a_sdk_version":"0.3.4"}
```

## 2. Local startup

```bash
cd lightspeed-stack
source .env                      # OPENAI_BASE_URL, E2E_OPENAI_MODEL, RH_SERVER_OKP, ENMAAS_KEY
uv run python src/lightspeed_stack.py -c lightspeed-stack.yaml
curl -s http://localhost:8080/a2a/health
```

## 3. Startup requirement that blocks the A2A surface

An agent card must be configured. With no `customization` section, every A2A
route fails — including `POST /a2a`, because the card is rebuilt per request in
`_create_a2a_app()`:

```
GET  /.well-known/agent-card.json -> 500 {"detail":"Customization configuration not found"}
GET  /.well-known/agent.json      -> 500 {"detail":"Customization configuration not found"}
POST /a2a                         -> 500 {"detail":"Customization configuration not found"}
```

Either form satisfies the requirement:

```yaml
customization:
  agent_card_config:   # inline
    name: "Lightspeed Assistant"
    ...
```

```yaml
customization:
  agent_card_path: agent_card.yaml   # or an external file
```

The deployment under test uses the inline form with `security: []`. A card with
no security schemes also makes the unauthenticated requirement explicit.

## 4. Endpoints and Agent Card

| Route | Method | Result |
| --- | --- | --- |
| `/.well-known/agent-card.json` | GET | 200, card |
| `/.well-known/agent.json` | GET | 200, identical card |
| `/a2a` | POST | 200, JSON-RPC envelope |
| `/a2a/health` | GET | 200 |

Captured card (abridged):

```json
{
  "name": "Lightspeed Assistant",
  "description": "Answers questions using Red Hat knowledge sources.",
  "protocolVersion": "0.3.0",
  "preferredTransport": "JSONRPC",
  "url": "http://localhost:8080/a2a",
  "version": "0.8.0rc1",
  "capabilities": {"streaming": true, "pushNotifications": false, "stateTransitionHistory": false},
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "security": [],
  "securitySchemes": {},
  "skills": [{
    "id": "red-hat-knowledge",
    "name": "Red Hat Knowledge Search",
    "tags": ["red-hat", "knowledge"],
    "inputModes": ["text/plain"],
    "outputModes": ["text/plain"]
  }]
}
```

The card describes a single generic query skill. It carries no per-skill
retrieval or evidence metadata; there is no way to discover which sources are
configured from the card.

## 5. JSON-RPC methods

### `message/send` — works without credentials

Request:

```json
{"jsonrpc":"2.0","id":"7053-1","method":"message/send","params":{"message":{
  "kind":"message","role":"user","messageId":"<uuid>",
  "parts":[{"kind":"text","text":"In one sentence: what is a Kubernetes pod?"}]}}}
```

Result is a Task (`kind: "task"`), completed in ~5.4 s:

```json
{
  "id": "be5f360e-...",
  "kind": "task",
  "contextId": "2a94b343-...",
  "status": {"state": "completed", "timestamp": "..."},
  "metadata": {"model": "openai/rits/zai-org/glm-5-3", "conversation_id": "1a5567fb..."},
  "artifacts": [{
    "artifactId": "ba44d7c9-...",
    "metadata": {"conversation_id": "1a5567fb..."},
    "parts": [{"kind": "text", "text": "A Kubernetes pod is the smallest deployable unit ..."}]
  }],
  "history": [ ... user and agent text messages ... ]
}
```

### `message/stream` — SSE, `data:` frames

Request uses `Accept: text/event-stream`. Event sequence:

1. `kind: "task"` with `status.state: "submitted"`
2. repeated `kind: "status-update"`, `final: false`, carrying `status.message` text deltas and
   `Tool call: <id> (mcp_server:okp)` entries
3. one `kind: "artifact-update"` with `lastChunk: true` and the final text artifact
4. `kind: "status-update"`, `final: true`, `status.state: "completed"`

### `tasks/get` — returns the stored task

```json
{"jsonrpc":"2.0","id":"7053-2","method":"tasks/get","params":{"id":"be5f360e-..."}}
```

Returns the same task object, including `artifacts` and full `history`.

### `tasks/cancel` — rejected for completed tasks

```json
{"error":{"code":-32002,"message":"Task cannot be canceled - current state: TaskState.completed"}}
```

The executor raises `NotImplementedError` for cancellation, so in-flight
cancellation is not available over A2A.

### Error handling

JSON-RPC errors are returned with **HTTP 200**, so clients must inspect the
`error` member, not the status code:

```json
{"jsonrpc":"2.0","id":"7053-7","error":{"code":-32603,"message":"TextPart content cannot be empty"}}
```

An empty input never produces a task in `input_required` state; it is a
transport-level error. Clarification therefore has to be implemented entirely in
the calling agent.

Failures inside execution terminate the task instead:

```json
"status": {"state": "failed",
           "message": {"parts": [{"kind":"text","text":"404: {'response': 'Model not found', ...}"}],
                       "role": "agent"}}
```

## 6. Evidence contract — absent over A2A, present over REST

This is the finding that matters most for the agent design. With
`rag.retrieval.tool.sources: [okp]` configured, the same query was sent to both
interfaces.

`POST /v1/query` returns structured evidence:

| Field | Observed shape |
| --- | --- |
| `rag_chunks[]` | `{content, score, source, attributes{chunk_id, parent_id, document_id, source, title}}` |
| `referenced_documents[]` | `{doc_url, doc_title, source: "okp", document_id}` |
| `tool_calls[]` / `tool_results[]` | `file_search` args plus raw results, including `chunk_id`, `parent_id` |
| `input_tokens` / `output_tokens` | `4441` / `1483` |
| `available_quotas` | `{}` |

`POST /a2a` `message/send` for the same query:

- Retrieval did run: six `file_search` tool calls appear in `history`.
- `artifacts[*].parts` is a single `{"kind": "text"}` part (6701 characters).
- `artifacts[*].metadata` is `{conversation_id}`; task `metadata` is
  `{model, conversation_id}`; `history` holds only `text` parts.
- The payload contains none of `rag_chunks`, `referenced_documents`, `doc_url`,
  `document_id`, `chunk_id`, `score`, `tool_results`, `input_tokens`,
  `output_tokens`, or `available_quotas`.
- The answer text embeds raw prompt markers such as
  `<|/documentation/en-us/openshift_container_platform/5.0/html-single/security_and_compliance/index|>`
  and contains no URLs at all. These markers are residue, not a citation
  contract.

**Conclusion:** retrieval and evidence exist upstream; the A2A executor keeps
only the final answer text and discards everything else. The blocking factor is
the A2A response shape, not retrieval. Evidence-dependent behavior (citations,
evidence-gap reasoning) needs an upstream A2A change to surface `rag_chunks` or
`referenced_documents` as artifact metadata or non-text parts. Until then an A2A
caller can only quote prose, and must not treat the inline markers as sources.

## 7. Source and model selection are caller-controllable

`message.metadata` is read for `model`, `provider`, and `vector_store_ids`.
Both were probed:

| Probe | Result |
| --- | --- |
| `metadata.model = "does-not-exist-7053"` | Task `failed`: `Model with ID does-not-exist-7053 does not exist` — the override is used |
| `metadata.vector_store_ids = ["nonexistent-store-7053"]` | Task `completed` with no error; the value is echoed in `history[*].metadata` |

Implications:

- A caller can select or break the model and can inject vector-store IDs.
- Server-side configuration is not authoritative by construction; it is only
  authoritative if the client never sends these fields.
- The Knowledge Search agent must send no message metadata at all, and tests
  should assert that the outgoing payload contains none of `model`, `provider`,
  `vector_store_ids`.

## 8. Token and cost limits — unsupported over A2A

- The A2A request has no field for token, cost, or budget limits, and the
  response reports no usage counters. The task object exposes only `artifacts`,
  `contextId`, `history`, `id`, `kind`, `metadata`, `status`.
- REST reports `input_tokens`, `output_tokens` and `available_quotas`; A2A
  reports none of them, so an A2A client cannot observe usage at all.
- Usage is recorded only as OpenTelemetry span attributes
  (`LLM_USAGE_INPUT_TOKENS` / `LLM_USAGE_OUTPUT_TOKENS`), which a caller cannot
  read over A2A.
- The A2A path does not participate in LCORE quota accounting.

**Conclusion:** an upstream token/cost cap cannot be requested or observed. The
agent must enforce its own limits and document this gap, per
`CONSTITUTION.md` §8. Latency observed: 3–5 s for a plain question, 37 s for a
RAG query over REST, and **70 s for the same RAG query over A2A** (six
`file_search` calls). The MVP's 30 s per-call limit will cut off realistic RAG
answers.

## 9. Authentication

Every call above was made with no credentials: card retrieval, `message/send`,
`message/stream`, `tasks/get`. No 401 responses occurred, and the card advertises
no security schemes. The MVP assumption that local LCORE needs no credentials
holds for this deployment.

## 10. Multi-turn continuity

Reusing a `contextId` continues the conversation: a follow-up (`"And how does it
differ from a container?"`) answered correctly using the earlier turn. Notes:

- The response `history` contains only the new turn, not the prior one; the
  conversation mapping is server-side `contextId` -> `conversation_id`.
- This deployment has no `a2a_state` section, so task and context state are
  in-memory and are lost on restart.

## 11. What this means for the agent

- Use `message/send` for the workflow; `message/stream` is available if progress
  reporting is wanted, but deltas are per-token noise.
- Send only the user's text: no `model`, `provider`, `vector_store_ids`, and no
  caller metadata passthrough.
- Budget with local limits, since upstream offers no quota or usage signal. Note
  that 30 s per call is below observed RAG latency (up to 70 s); the limit needs
  raising or the workflow needs streaming with progress reporting.
- Do not promise citations. Answers may contain raw `<|/documentation/...|>`
  markers, which are prompt residue and must not be presented as sources. Either
  label answers as model-generated without verifiable evidence, or gate evidence
  features until LCORE surfaces `rag_chunks` or `referenced_documents` over A2A.
- Clarification is entirely the agent's responsibility; LCORE never returns
  `input_required` for missing context.
- Treat `history` as diagnostic only; never relay it to callers.

## 12. Answers to `docs/open-questions.md`

| Question | Answer |
| --- | --- |
| 1. Evidence over A2A | No, although REST has it. `/v1/query` returns `rag_chunks` and `referenced_documents` with URLs, IDs, scores and sources; A2A artifacts are single text parts carrying only `conversation_id`. Retrieval still runs, so the loss is in the A2A response shape. |
| 2. Source selection | Caller metadata is accepted (`model`, `provider`, `vector_store_ids`). The agent must omit it; server-side configuration is authoritative only by client discipline. Retrieval is configured as OKP via `rag.retrieval.tool`. |
| 3. Auth and caller context | Not required locally (`noop`, `auth_enabled: false`). No identity delegation mechanism was exercised. |
| 4. Quota and limits | No upstream quota or usage reporting on A2A; REST exposes token counts and `available_quotas` (empty in this deployment). Local limits are mandatory, and 30 s per call is too low for RAG. |
| 5. Clarification and continuity | `contextId` reuse works for multi-turn. Clarification states are not produced by LCORE; cancelled tasks are rejected. State is in-memory in this deployment. |

## 13. Repeatable capture commands

```bash
curl -s http://localhost:8080/.well-known/agent-card.json
curl -s http://localhost:8080/a2a/health

curl -s -X POST http://localhost:8080/a2a \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{
       "kind":"message","role":"user","messageId":"<uuid>",
       "parts":[{"kind":"text","text":"In one sentence: what is a Kubernetes pod?"}]}}}'

curl -s -N -X POST http://localhost:8080/a2a \
  -H 'Content-Type: application/json' -H 'Accept: text/event-stream' \
  -d '{"jsonrpc":"2.0","id":"2","method":"message/stream","params":{"message":{
       "kind":"message","role":"user","messageId":"<uuid>",
       "parts":[{"kind":"text","text":"In one sentence: what is an OpenShift route?"}]}}}'

curl -s -X POST http://localhost:8080/a2a \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"3","method":"tasks/get","params":{"id":"<task-id>"}}'

# Reference evidence shape on the REST path, for comparison
curl -s -X POST http://localhost:8080/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is the documented procedure to rotate cluster certificates on OpenShift?"}'
```

Client-side rules derived from the captures:

- Check the JSON-RPC `error` member; HTTP status is 200 even for errors.
- Read the answer from `artifacts[0].parts[*].text`.
- Persist `contextId` if multi-turn continuity is needed; persist `id` for `tasks/get`.

## 14. Upstream follow-ups

- LCORE evidence contract: still an open upstream gap.
- OKP MCP missing evidence: not tracked yet; tracker and owner still to be
  identified.

## 15. Implications for agent-owned reasoning

The target foundation moves control-plane reasoning into the agent and keeps
LCORE as the A2A knowledge service. This report still applies:

- LCORE answer text is the only material available over A2A today. The agent
  model must treat it as untrusted data, not as instructions or a citation
  contract.
- `referenced_documents` or an equivalent artifact-metadata evidence envelope is
  required before the agent can present verified Sources. Until then answers are
  labeled unverified.
- The agent must not ask LCORE to consolidate answers, choose a follow-up, or
  format the final response. Those are agent-owned model calls.
- Each agent search starts a fresh LCORE conversation. The agent does not reuse
  `contextId`, so LCORE turn history cannot become hidden context for a later
  search.
- The agent sends no message metadata. LCORE's caller-controllable `model`,
  `provider`, and `vector_store_ids` fields remain off-limits.
- The 90 s per-call and 180 s per-task defaults remain appropriate for the
  measured A2A latency; the agent adds its own model-request, token, and deadline
  limits around the LCORE calls.
