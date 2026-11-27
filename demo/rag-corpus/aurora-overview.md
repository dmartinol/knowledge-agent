---
title: Aurora Deploy overview
url: https://docs.aurora.invalid/overview
---

# Aurora Deploy overview

Aurora Deploy is a fictional delivery platform used by this demo. It packages an
application as a *blueprint* and rolls it out to one or more *lanes*. Every
statement in this directory is invented for demonstration purposes and does not
describe a real product.

## Core concepts

- **Project** — the ownership boundary. Quotas, secrets, and rollback history
  belong to a project, not to a blueprint.
- **Blueprint** — a versioned description of an application: image reference,
  ports, health checks, and a list of lanes.
- **Lane** — an ordered delivery stage such as `edge`, `staging`, or `prod`.
  A blueprint may target several lanes at once.
- **Gate** — a check that must pass before a lane advances. Aurora Deploy ships
  the `smoke` and `soak` gates; teams can add their own.

## Default behaviour

`aurora apply` walks the lanes in the order they appear in the blueprint. A lane
is considered complete when every replica reports ready for two consecutive
probes. If a lane fails, the rollout stops there and the previous revision keeps
serving traffic.

The platform keeps the last five revisions of every blueprint. `aurora rollback`
takes a revision number; without an argument it selects the previous one.
