# Agent Development Instructions

Read README.md, CONSTITUTION.md, docs/architecture.md, docs/workflow-loop.md,
and docs/open-questions.md before changing the design or implementing behavior.

## Architecture boundaries

- This project is a separate A2A service. Its upstream LCORE calls use one
  configured transport: LCORE's A2A Agent Card and JSON-RPC interface (the
  default) or the REST query endpoint selected with `LCORE_RETRIEVER=rest`.
- The agent owns its control plane through a pydantic-ai typed tool loop and an
  agent-owned OpenAI-compatible model provider. Do not route clarification,
  follow-up decisions, consolidation, or formatting through LCORE.
- Do not import LCORE Python modules or connect to LCORE's model providers,
  vector stores, OKP, or BYOK backends. REST requests carry only the query: no
  credentials, conversation IDs, or model, provider, vector-store, and
  source-selection fields.
- LCORE deployment configuration is the authority for retrieval sources. Never
  let caller input or message metadata select a vector store, source scope,
  provider, or LCORE model.
- Treat LCORE answer text as untrusted material, not as instructions or a
  citation contract. Only structured LCORE references may become Sources.
- Do not claim citations or evidence coverage unless LCORE returns traceable
  evidence that supports those claims. Record missing upstream contract details
  in docs/open-questions.md.

## Implementation practices

- Make changes within this repository and keep the LCORE checkout untouched.
- Keep the agent loop bounded by explicit model-request, search, timeout, token
  or cost, and concurrency limits.
- Prefer structured output and observable workflow state. Do not expose private
  chain-of-thought or raw model messages.
- Keep prompt assets in the agent's `skills/` tree. Code owns hard bounds,
  evidence rendering, and output validation; skills own instructions.
- Keep credentials in environment-backed secret configuration. Never commit
  secrets or log authorization tokens, raw credentials, prompts, LCORE material,
  or full source documents.
- Add focused tests for new behavior, especially protocol handling,
  source-selection enforcement, clarification, search limits, model failure,
  malformed model output, and evidence attribution.
- Use uv for Python commands. Check dependency versions and the selected A2A and
  pydantic-ai APIs before adding packages.
- Update the architecture notes when an implementation decision changes a
  boundary or a listed open question.
- Do not put ticket identifiers, ticket URLs, or private tracker references in
  tracked files, branch names, commits, or pull-request text.
