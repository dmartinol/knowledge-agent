---
title: Aurora CLI reference
url: https://docs.aurora.invalid/cli
---

# Aurora CLI reference

The `aurora` command groups its verbs by area: `project`, `blueprint`, `lane`,
and `quota`. The most used verbs are listed here.

## aurora doctor

`aurora doctor` is the pre-flight diagnostics command introduced in release
2.4.0. It performs exactly three checks and prints one line per check:

1. **Clock skew** — compares the workstation clock with the control plane and
   warns when the difference exceeds 90 seconds.
2. **Certificate expiry** — reports the embedded control-plane certificate and
   fails when fewer than 30 days remain.
3. **Registry DNS** — resolves the registry mirror hostname and fails when the
   lookup returns no address.

`aurora doctor` never modifies state. Use `--verbose` to print the resolved
hostnames as well.

## Other verbs

- `aurora apply --blueprint <file>` — create or update a blueprint and roll it
  out. Replaces the deprecated `aurora deploy` verb.
- `aurora rollback --revision <n>` — return a blueprint to an earlier revision.
- `aurora quota show --project <name>` — print the project quota and its usage.
- `aurora lane hold --lane <name>` — stop new revisions from entering a lane.
