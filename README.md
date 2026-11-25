# Knowledge Search Agent

A proof of concept for an A2A agent that provides evidence-aware knowledge search, using Lightspeed Core Stack (LCORE) as a service.

## Initial architecture

This repository owns the Knowledge Search agent and its A2A interface. It calls LCORE through LCORE's A2A interface for model and retrieval work.

- The agent owns a bounded query workflow: decide when to clarify, form follow-up queries, assess returned evidence, and communicate an answer or an evidence gap.
- LCORE owns model serving, retrieval execution, and the administrator-configured OKP and BYOK sources and credentials.
- Callers cannot select vector stores or change LCORE configuration. The agent must not forward caller-provided source identifiers to LCORE.
- The query path uses A2A between the agent and LCORE. The agent does not import LCORE internals or connect directly to its vector databases.

See [the architecture notes](docs/architecture.md) and [open questions](docs/open-questions.md) before implementing the runtime.

## Integration constraint to resolve first

The current LCORE A2A path is a general query agent and returns a text artifact. Confirm whether its A2A response provides traceable source references or excerpts before promising citations or evidence-grounded retry behavior. The agent must not invent citations from a generated answer.

The current LCORE A2A handler accepts vector-store identifiers in message metadata, and its A2A route does not currently use LCORE quota accounting. The agent must omit source-selection metadata and enforce strict local limits while the upstream quota policy is clarified.

## Development

This is a documentation-first scaffold. Runtime dependencies and the agent framework will be chosen after the A2A evidence and authentication contracts are validated.

Use uv for Python development commands. Keep the project independent from the LCORE checkout; do not copy its dependency set wholesale.
