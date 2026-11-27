---
title: Aurora networking
url: https://docs.aurora.invalid/networking
---

# Aurora networking

This chapter describes how Aurora Deploy exposes a blueprint and how hostnames
are formed. Aurora Deploy is fictional; names below are illustrative.

## Hostname formation

A published service receives a hostname with the shape

```
<service>-<project>-<cluster>.aurora.example
```

The service name is taken from the blueprint, lowercased, with underscores
replaced by hyphens. The project is the project that owns the blueprint. The
cluster suffix is fixed per Aurora installation.

Hostnames are generated once, when the service is first published. Renaming a
service later keeps the original hostname until the operator deletes and
recreates it.

## Ports

A blueprint declares at most one *public* port. That port is published on
hostname port 443 only; other declared ports stay reachable inside the cluster
network. A blueprint that declares two public ports is rejected at `aurora apply`
time with the error code `AUR-1042`.

## Health checks

Lanes advance only when the health check passes. The check may use HTTP, TCP, or
a command executed inside the container. Command checks time out after 20
seconds.
