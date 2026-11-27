---
title: Aurora Deploy release notes
url: https://docs.aurora.invalid/release-notes
---

# Aurora Deploy release notes

Release notes for the fictional Aurora Deploy platform. Only the entries that
matter for the demo corpus are kept.

## 2.4.0

- Added `aurora doctor`, a read-only pre-flight check for clock skew,
  certificate expiry, and registry DNS.
- Renamed `aurora deploy` to `aurora apply`; the old verb still works but prints
  a deprecation warning.
- Lane events now record the gate that blocked a rollout.

## 2.3.2

- Fixed hostname regeneration when a service was renamed after publication.
- `aurora rollback` no longer needs a revision argument.

## 2.3.0

- Projects gained their own certificate store.
- Default project quota gained the active build limit of 3.
