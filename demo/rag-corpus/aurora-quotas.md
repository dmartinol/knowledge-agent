---
title: Aurora project quotas
url: https://docs.aurora.invalid/quotas
---

# Aurora project quotas

Aurora Deploy applies a default quota to every new project. The numbers below
are invented for the demo corpus.

## Defaults per project

| Resource | Default limit |
| --- | --- |
| ConfigMaps | 12 |
| Services | 6 |
| Concurrent builds | 3 |
| Stored revisions per blueprint | 5 |
| Uploaded certificates | 4 |

`aurora quota show --project <name>` prints the limits next to current usage.

## Raising a quota

Quotas are raised per project with `aurora quota raise --project <name>
--resource <resource> --limit <number>`. The request is recorded in the project
audit trail and needs approval from a platform owner. Requests above twice the
default limit need two approvals.

## Behaviour at the limit

When a project reaches a limit, the next `aurora apply` fails with error code
`AUR-2001` and names the exhausted resource. Existing workloads keep running.
