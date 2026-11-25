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

## Controlled workflow

1. Validate the caller's request and check whether ambiguity would change the search target.
2. Ask a clarification question when needed; otherwise send a focused query to LCORE.
3. Assess the returned evidence for relevance and coverage.
4. Retry only for a specific, explainable gap and only within configured limits.
5. Answer with supported evidence references, or state what the evidence does not establish.

The workflow may store a short structured plan and evidence assessment. It does not expose hidden chain-of-thought.

## Known constraints

- The current LCORE A2A handler is a general query path, not a dedicated raw-retrieval API.
- The current LCORE A2A response is text-oriented. Evidence identifiers, source excerpts, and citation guarantees need validation.
- LCORE's current A2A path does not use standard LCORE quota accounting. Local limits are required until the upstream policy is clarified.
- LCORE currently accepts vector-store IDs in request metadata. This service must not set that field, and server-side configuration must remain authoritative.

See [open questions](open-questions.md) for the validation checklist.
