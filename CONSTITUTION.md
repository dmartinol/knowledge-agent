# Knowledge Search Agent Constitution

## 1. Mission

Provide an A2A knowledge-search service that helps callers reach useful answers through LCORE while preserving evidence provenance and making uncertainty clear.

## 2. LCORE owns retrieval configuration

OKP and BYOK sources are configured by the LCORE administrator. The agent and its callers do not choose arbitrary vector-store IDs, source scopes, credentials, or model providers. The agent may refine a query, but it may not widen or change the configured source set.

## 3. Evidence must be verifiable

Only cite sources, document identifiers, or excerpts actually returned through a supported LCORE interface. Distinguish source evidence from the agent's synthesis. If the upstream response does not carry enough evidence to support an answer, state that limitation and report the evidence gap; never fabricate citations.

## 4. Search is bounded and purposeful

Use a controlled workflow with explicit limits for rounds, backend calls, time, and model usage. Search again only when the prior result identifies a concrete coverage gap or a materially better query. Ask for clarification when ambiguity changes what should be searched.

## 5. Explain outcomes without exposing private reasoning

Return the answer, relevant evidence references, clarification requests, or the reason the evidence is insufficient. Do not expose hidden chain-of-thought. Keep workflow state concise and suitable for logs and tests.

## 6. Preserve the A2A service boundary

The agent exposes A2A to its callers and uses LCORE A2A for upstream query work. Keep LCORE-specific transport mapping at an adapter boundary. Do not couple this project to LCORE's internal Python packages or databases.

## 7. Protect caller and source data

Treat caller messages and metadata as untrusted. Forward only the input and authentication context required by the documented protocol. Do not log secrets or source content by default. Keep upstream credentials in deployment-managed secret configuration.

## 8. Bound operational cost

LCORE's current A2A path does not apply its standard quota accounting. Until an upstream policy is established, enforce local limits on concurrent tasks, A2A calls, retries, time, and model usage. Fail clearly when a limit is reached.

## 9. Keep platform assumptions explicit

Do not describe planned LCORE behavior as available behavior. Track protocol gaps and assumptions in docs/open-questions.md, and resolve them against the deployed LCORE version before relying on them.
