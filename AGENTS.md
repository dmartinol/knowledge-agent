# Agent Development Instructions

Read README.md, CONSTITUTION.md, docs/architecture.md, and docs/open-questions.md before changing the design or implementing behavior.

## Architecture boundaries

- This project is a separate A2A service. Its upstream LCORE calls use LCORE's A2A Agent Card and A2A JSON-RPC interface.
- Do not use LCORE REST query endpoints, import LCORE Python modules, or connect directly to its model providers, vector stores, OKP, or BYOK backends unless the architecture is explicitly reconsidered.
- LCORE deployment configuration is the authority for retrieval sources. Never let caller input or message metadata select a vector store, source scope, provider, or model.
- Do not claim citations or evidence coverage unless LCORE returns traceable evidence that supports those claims. Record missing upstream contract details in docs/open-questions.md.

## Implementation practices

- Make changes within this repository and keep the LCORE checkout untouched.
- Keep the agent loop bounded by explicit request, round, timeout, and token or cost limits.
- Prefer structured decisions and observable workflow state. Do not expose private chain-of-thought.
- Keep credentials in environment-backed secret configuration. Never commit secrets or log authorization tokens, raw credentials, or full source documents.
- Add focused tests for new behavior, especially protocol handling, source-selection enforcement, clarification, retry limits, and evidence attribution.
- Use uv for Python commands. Check dependency versions and the selected A2A SDK APIs before adding packages.
- Update the architecture notes when an implementation decision changes a boundary or a listed open question.
