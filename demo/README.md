# Knowledge Search Agent demo

A self-contained demo of the Knowledge Search Agent, its browser console, and an
in-cluster Lightspeed Core (LCORE) retrieval service. Everything demo-specific
lives under `demo/` so the repository root stays focused on the agent runtime.

The console drives the agent over real A2A JSON-RPC (`message/send` with
`blocking: false` plus `tasks/get` polling). It never talks to LCORE directly and
never sees a model credential. LCORE is the retrieval data plane; the agent owns
reasoning, clarification, and answer rendering.

## Layout

| Path | Purpose |
| --- | --- |
| `demo/agent/Containerfile` | Agent image. Build context is the repository root; the `skills/` tree is baked in. |
| `demo/ui/` | React + Vite + PatternFly console, plus the Express bundle server/proxy. |
| `demo/chart/knowledge-agent/` | Helm chart for the agent, console, LCORE, Routes, and NetworkPolicies. |
| `demo/chart/knowledge-agent/values-secret.yaml.example` | Secret template; the chart never renders secret material. |

## Prerequisites

- An OpenShift 4.16+ cluster where you can create a project, builds, Routes, and NetworkPolicies.
- `oc`, `helm` 3.14+, and `podman` or `docker` for local images.
- An OpenAI-compatible model endpoint and API key for the agent (the agent's reasoning model).
- An RHOKP endpoint reachable from the LCORE pod. The chart assumes RHOKP runs in
  the `rhokp` namespace at `http://rhokp.rhokp.svc.cluster.local:8080`; change
  `RH_SERVER_OKP` and `networkPolicy.rhokpNamespace` if yours differs.
- An LCORE inference endpoint/key. In library mode LCORE uses the same
  OpenAI-compatible provider settings (`OPENAI_BASE_URL`, `OPENAI_API_KEY`).

LCORE is deployed in-cluster in OGX library mode (`ogx.use_as_library_client:
true`, `baseline: byo-llm`), so there is no separate OGX pod. The image is
pinned in `values.yaml`.

## Build the images

The chart defaults to the ImageStreams `knowledge-agent-demo` and
`knowledge-agent-demo-ui`. Build both in the target namespace.

```bash
export NS=knowledge-agent-demo
oc new-project "$NS"

# Agent: context is the repository root, Dockerfile lives under demo/agent.
oc new-build --binary --strategy=docker --name=knowledge-agent-demo \
  --dockerfile=demo/agent/Containerfile -n "$NS"
tar --exclude=.git --exclude=.venv --exclude=node_modules --exclude=dist \
  --exclude='.pytest_cache' --exclude='.ruff_cache' -czf - . \
  | oc start-build knowledge-agent-demo --from-archive=- --follow -n "$NS"

# Console: context is demo/ui.
oc new-build --binary --strategy=docker --name=knowledge-agent-demo-ui \
  --dockerfile=Containerfile -n "$NS"
```

Run the console build from `demo/ui`:

```bash
(cd demo/ui && tar --exclude=node_modules --exclude=dist -czf - .) \
  | oc start-build knowledge-agent-demo-ui --from-archive=- --follow -n "$NS"
```

Both builds create `:latest` images in the namespace's ImageStreams. By default
the chart pulls
`image-registry.openshift-image-registry.svc:5000/<namespace>/<stream>:latest`,
because plain Deployments do not resolve short ImageStream names. To use
prebuilt images elsewhere, set `agent.image.repository` and
`ui.image.repository` to full repositories (without a tag).

## Configure secrets

Create one Secret and give the chart its name. It carries the agent key, the
LCORE inference key and endpoint, and the RHOKP URL. Nothing from it is rendered
into a ConfigMap, an image, or the console bundle.

```bash
cp demo/chart/knowledge-agent/values-secret.yaml.example /tmp/knowledge-agent-secrets.yaml
# edit /tmp/knowledge-agent-secrets.yaml
oc apply -f /tmp/knowledge-agent-secrets.yaml -n "$NS"
```

The Secret keys default to `AGENT_LLM_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
and `RH_SERVER_OKP`; override them under `secrets.keys` if you use different
names.

## Install

```bash
helm install knowledge-agent demo/chart/knowledge-agent -n "$NS" \
  --set secrets.existingSecret=knowledge-agent-secrets \
  --set agent.llm.baseUrl=https://your-model-endpoint.example/v1 \
  --set agent.llm.model=your-model
```

Watch the rollout. LCORE can take 60–120 s before it listens on port 8080.

```bash
oc get pods -n "$NS" -w
oc get route -n "$NS"
```

## Verify

```bash
UI_HOST=$(oc get route knowledge-agent-ui -n "$NS" -o jsonpath='{.spec.host}')
AGENT_HOST=$(oc get route knowledge-agent -n "$NS" -o jsonpath='{.spec.host}')

curl -sk "https://$UI_HOST/healthz"
curl -sk "https://$UI_HOST/.well-known/agent-card.json" | jq '{name, version, url}'
curl -sk "https://$AGENT_HOST/a2a/health"
```

Send a non-blocking request and read the workflow metadata, including how many
searches and model requests the run used:

```bash
TASK=$(curl -sk "https://$UI_HOST/a2a" -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0", "id": "1", "method": "message/send",
  "params": {
    "message": {"kind": "message", "role": "user", "messageId": "curl-1",
      "parts": [{"kind": "text", "text": "Explain how an OpenShift Route exposes a Service."}]},
    "configuration": {"blocking": false, "acceptedOutputModes": ["text/plain"]}
  }
}' | jq -r '.result.id')

curl -sk "https://$UI_HOST/a2a" -H 'Content-Type: application/json' -d "{
  \"jsonrpc\": \"2.0\", \"id\": \"2\", \"method\": \"tasks/get\", \"params\": {\"id\": \"$TASK\"}
}" | jq '.result | {state: .status.state, meta: .artifacts[-1].metadata.knowledge_agent}'
```

The console shows the same data in its inspector: decision source, searches
against the cap, model requests and tokens, limits hit, evidence support, and
the raw A2A exchange.

### Routing expectations

- `https://$UI_HOST/` serves the console over TLS.
- `https://$AGENT_HOST/a2a` is the A2A JSON-RPC endpoint for the A2A Inspector.
- The console proxies `/a2a` and `/.well-known/*` to the agent Service, so the
  browser only needs the console Route.

## Manual acceptance run

1. **Evidence-backed answer** – ask about OpenShift Route hostname generation or
   TLS termination. Expect a completed answer.
2. **Ambiguous request** – send `Tell me about it.`. Expect `input-required` and
   one clarification card; answer it and confirm the *same* task continues.
3. **No evidence** – ask for an internal release date. Expect the unverified
   limitation banner and no Sources section.
4. **Search limit** – ask for a broad networking overview. Expect the
   search-limit gap and `limits_hit: ["search"]` in the inspector.

## Fail-fast runbook

Prove the bounded failure path without deleting anything:

```bash
# Temporarily override the agent key with an invalid value.
oc set env deployment/knowledge-agent AGENT_LLM_API_KEY=invalid -n "$NS"
oc rollout status deployment/knowledge-agent -n "$NS"

# Ask a question in the console. Expect a friendly failure alert and a stable
# code such as model_config_error or model_unavailable.

# Restore the chart-managed secret reference and restart the pod.
helm upgrade knowledge-agent demo/chart/knowledge-agent -n "$NS" --reuse-values
oc rollout status deployment/knowledge-agent -n "$NS"
```

The console also stops polling after 200 s and reports `ui_timeout` instead of
hanging forever.

## Upgrade and uninstall

```bash
helm upgrade knowledge-agent demo/chart/knowledge-agent -n "$NS" --reuse-values
helm uninstall knowledge-agent -n "$NS"
```

Reusing an existing LCORE instead of deploying one:

```bash
helm upgrade knowledge-agent demo/chart/knowledge-agent -n "$NS" --reuse-values \
  --set lcore.enabled=false \
  --set lcore.externalUrl=http://lightspeed-stack.other-namespace.svc.cluster.local:8080
```

## Local run (no cluster)

1. Start LCORE from the lightspeed-stack checkout with the captured
   configuration (`docs/lcore-a2a-contract/lightspeed-stack.yaml`) on port 8080.
2. Start the agent with its model settings:

   ```bash
   LCORE_AGENT_CARD_URL=http://127.0.0.1:8080/.well-known/agent-card.json \
   uv run --env-file .env knowledge-agent   # serves :8081
   ```

3. Start the console with the Vite dev proxy:

   ```bash
   cd demo/ui && npm ci && npm run dev      # http://127.0.0.1:5173
   ```

   For a production-style local run, build the bundle and use the Express
   server:

   ```bash
   cd demo/ui && npm ci && npm run build
   AGENT_INTERNAL_URL=http://127.0.0.1:8081 npm start   # serves :8080
   ```

The Vite dev proxy forwards `/a2a` and `/.well-known/*` to
`AGENT_INTERNAL_URL` (default `http://127.0.0.1:8081`), so the browser always
uses same-origin URLs.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| LCORE pod not ready for minutes | Normal during startup; `oc logs deploy/knowledge-agent-lcore`. Readiness is a TCP probe with a long failure threshold. |
| Agent CrashLoop with `configuration error` | Missing `AGENT_LLM_BASE_URL`, `AGENT_LLM_MODEL`, `AGENT_LLM_API_KEY`, or an unusable `AGENT_SKILLS_DIR`. |
| Console shows `agent_unreachable` | The UI proxy could not reach the agent Service. Check `AGENT_INTERNAL_URL`, pod readiness, and the UI egress NetworkPolicy. |
| `card_unavailable` in a run | LCORE is not ready or the agent→LCORE NetworkPolicy/service name is wrong. |
| `model_config_error` or HTTP 401 | Invalid agent key or model name. |
| LCORE returns no evidence | Expected until the upstream structured-evidence contract lands; the answer is labelled unverified. |
| Agent Card advertises `0.0.0.0` | Set `agent.publicUrl` (and optionally `agent.route.host`) and upgrade. |
| Route answers 503 | The pod is not Ready, or the ingress NetworkPolicy selector does not match your router namespace. |
| Console proxy returns 502 `agent_unreachable` and the UI pod logs `EAI_AGAIN` | The console cannot resolve cluster DNS while egress-isolated. Some clusters re-originate DNS from the node, so port-53 rules never match. Set `networkPolicy.uiAllowAnyEgress=true`; the console keeps working but its egress is no longer scoped to the agent. |
| Blocking `message/send` through a Route returns the router's 504 page | The call outlived the router timeout. Both Routes carry `haproxy.router.openshift.io/timeout` from `agent.route.timeout` / `ui.route.timeout` (default `240s`). |
| UI binary build sits in `npm ci` for tens of minutes | The default 500m build limit starves `npm ci`; raise `spec.resources.limits` on the BuildConfig (2 CPU cut it to under four minutes). |
| LCORE answers `failed` / "Internal server error" and logs `ModelHTTPError` from the provider | The provider rejected the LCORE request shape or model. Check the provider directly with the same model id before changing the chart. |
| LCORE exits with `ModelDiscoveryError` | The provider entry lost its key or endpoint; see the two-consumer note in `templates/lcore-configmap.yaml`. |

## Design notes

**Why not Next.js.** The console is a single screen with no routing, SSR, or
SEO needs. Vite builds a static bundle, and a ~60-line Express server serves it
plus the same-origin A2A proxy. That keeps the image small and the proxy logic
explicit. Next.js would add a server runtime and routing layer we would not use.

**Why the demo owns an LCORE Deployment.** There is no released Helm chart or
operator for lightspeed-stack in this demo's scope. The chart embeds a minimal
Deployment modeled on the upstream end-to-end manifests: config mounted as a
`subPath` file, an `emptyDir` at `/tmp/data`, library-mode OGX, and TCP probes.
For production, use the LCORE deployment mechanism of your platform and point
the chart at it with `lcore.enabled=false` and `lcore.externalUrl`.

**Network boundaries.** The console can reach only the agent; the agent can
reach only LCORE and the model endpoint; LCORE can reach only RHOKP and the
model endpoint. Ingress to the agent is allowed from the OpenShift router and
from the console pods. External egress is controlled by
`networkPolicy.externalEgress`; set CIDRs there to narrow it.

**Two consumers read the LCORE provider entry.** LCORE's startup model
discovery reads `inference.providers[].config`, while the OGX `run.yaml` it
synthesizes at boot ignores that block and only understands `api_key_env` and
the `extra` escape hatch. The chart sets both and keeps them from the same
values, so neither path loses the key or the endpoint.

**The card must advertise a reachable endpoint.** LCORE publishes
`service.base_url` in its Agent Card; without it the card advertises
`localhost`, and the A2A client reports the unreachable endpoint as
`503 Network communication error`. The chart sets it to the in-cluster Service
(`lcore.serviceBaseUrl` overrides), and the client also rewrites loopback card
endpoints to the host it fetched the card from.
