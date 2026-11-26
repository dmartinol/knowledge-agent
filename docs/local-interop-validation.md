# Local interoperability validation

Repeatable local checks for the A2A surface of the Knowledge Search agent. The
protocol-level checks use `curl`; the A2A Inspector provides the same view in a
browser.

## Prerequisites

- LCORE is running locally and serves its Agent Card at
  `http://localhost:8080/.well-known/agent-card.json`.
- `.env` sets `AGENT_LLM_BASE_URL`, `AGENT_LLM_MODEL`, and `AGENT_LLM_API_KEY`.
- The `skills/` tree is present, or `AGENT_SKILLS_DIR` points at it.

## Run the agent

```bash
uv sync
uv run --env-file .env knowledge-agent
```

Startup must print the model, provider, public URL, LCORE card URL, and the
loaded skills:

```
INFO knowledge_agent: Knowledge agent starting: model=<model> provider=<base-url> public_url=http://127.0.0.1:8081 lcore_card=http://localhost:8080/.well-known/agent-card.json
INFO knowledge_agent: Skills loaded from skills: knowledge-search@2 sha256=<prefix>, answer-synthesis@2 sha256=<prefix>
```

Missing or unusable skills, or an incomplete `AGENT_LLM_*` set, exits with code 2
before the server starts.

## Install the Inspector

The inspector is a developer tool, not a dependency of the agent, so install it
on the workstation only. This validation was done with `1.0.0-alpha.2`.

Download the archive for your OS and architecture from the
[A2A Inspector releases](https://github.com/a2aproject/a2a-inspector/releases),
verify it against the published `checksums.txt`, and put the binary on `PATH`.
For macOS on Apple Silicon:

```bash
version=1.0.0-alpha.2
asset=a2a-inspector_${version}_darwin_arm64.tar.gz
base=https://github.com/a2aproject/a2a-inspector/releases/download/v${version}
curl -sSLO "$base/$asset"
curl -sSLO "$base/checksums.txt"
shasum -a 256 -c checksums.txt --ignore-missing
tar -xzf "$asset" a2a-inspector
install -m 0755 a2a-inspector ~/.local/bin/
```

`shasum -c` prints `OK` for the asset you downloaded. Substitute
`darwin_amd64`, `linux_amd64`, or `linux_arm64` for another platform, or use the
matching `windows_*.zip`. Equivalent options are
`go install github.com/a2aproject/a2a-inspector@v${version}` and
`docker run --rm -p 127.0.0.1:8090:8080 ghcr.io/a2aproject/a2a-inspector:v${version}`,
where the container reaches the agent as `host.docker.internal:8081`.

The release binary is not notarized. If macOS refuses to run it, clear the
quarantine flag once:

```bash
xattr -d com.apple.quarantine ~/.local/bin/a2a-inspector
```

## Inspect in the browser

```bash
a2a-inspector --port 8090 -a localhost:8081 --no-open
```

`--no-open` keeps the inspector from taking over the default browser, and
`-a localhost:8081` preloads the agent's card. Open the tokenized URL the
inspector prints; the token is per run, so it stops working when the process
restarts and the browser needs the new URL.

The tabs are `Chat`, `Tasks`, `Traffic`, and `Validation`. Confirm the card is
accepted (v0.3, JSON-RPC interface `http://127.0.0.1:8081/a2a`), send a message
from the Chat tab, and check that the Traffic tab shows the card fetch,
`message/send`, and `tasks/get`. When the agent returns `input-required`, the
Chat tab shows the clarification and the next message continues the same task,
which exercises `taskId` continuity.

## Protocol checks with curl

```bash
curl -s http://127.0.0.1:8081/a2a/health
curl -s http://127.0.0.1:8081/.well-known/agent-card.json
```

Send a message:

```bash
curl -s http://127.0.0.1:8081/a2a \
  -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":\"1\",\"method\":\"message/send\",\"params\":{\"message\":{\"kind\":\"message\",\"messageId\":\"$(uuidgen)\",\"role\":\"user\",\"parts\":[{\"kind\":\"text\",\"text\":\"hello\"}]},\"configuration\":{\"blocking\":true,\"acceptedOutputModes\":[\"text/plain\"]}}}" |
  jq '.result.status'
```

Resume a task that returned `input-required` by sending the same `taskId` and
`contextId` with `"subject"` replaced by the clarification answer:

```bash
curl -s http://127.0.0.1:8081/a2a \
  -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":\"2\",\"method\":\"message/send\",\"params\":{\"message\":{\"kind\":\"message\",\"messageId\":\"$(uuidgen)\",\"taskId\":\"<taskId>\",\"contextId\":\"<contextId>\",\"role\":\"user\",\"parts\":[{\"kind\":\"text\",\"text\":\"How do OpenShift routes expose a service externally?\"}]},\"configuration\":{\"blocking\":true,\"acceptedOutputModes\":[\"text/plain\"]}}}" |
  jq '.result.artifacts[0].metadata.knowledge_agent'
```

Read a task back:

```bash
curl -s http://127.0.0.1:8081/a2a \
  -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":\"3\",\"method\":\"tasks/get\",\"params\":{\"id\":\"<taskId>\"}}" |
  jq '.result.status'
```

## Expected outcomes

| Case | How to trigger | Expected |
| --- | --- | --- |
| Discovery | `GET /.well-known/agent-card.json` | Card with JSON-RPC interface at `/a2a` |
| Clarification | Send `hello` | `input-required`, one question, no LCORE call |
| Resume | Reply with the same `taskId` | `completed` answer, `clarification_used=true` |
| Synthesis | Any answered question | Prose answer only; `Sources` only from `support=retrieved` references |
| Unverified | LCORE returns no structured references | `evidence_status=unavailable` and a `Limitation: Unverified` line |
| Upstream timeout | Slow LCORE query with the default 90 s call timeout | `failed`, `error=timeout` |
| Model unreachable | `AGENT_LLM_BASE_URL` pointing at a closed port | `failed`, `error=model_unavailable` |
| Model limit | `AGENT_LLM_REQUEST_LIMIT=1` | `failed`, `error=model_limit`, `limits_hit=["model_requests"]` |
| Skills | Agent startup log | `knowledge-search@<version>` and `answer-synthesis@<version>` with digests |

## Automated coverage

`uv run pytest -q` covers the follow-up cap, the third-search `limit_reached`
observation, output validation and retries, token and request limits, evidence
rendering, no caller source selection, and the absence of caller metadata on the
LCORE call. Those paths are deterministic with a fake model and do not need a
live provider.
