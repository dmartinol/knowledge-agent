---
title: Aurora TLS handling
url: https://docs.aurora.invalid/tls
---

# Aurora TLS handling

Aurora Deploy terminates TLS at the lane edge by default. This document is part
of a fictional demo corpus.

## Default certificates

Every published service gets a certificate for its generated hostname. Aurora
renews the certificate automatically 21 days before expiry. The renewal is
visible in `aurora lane status --events`.

## Bring your own certificate

A project may upload a certificate and key with
`aurora project certificate upload`. When a project certificate matches the
service hostname, Aurora uses it instead of the generated one. Uploaded
certificates are not renewed automatically; `aurora doctor` reports the nearest
expiry date for every uploaded certificate.

## Mixed termination

A blueprint may ask for *pass-through* instead of termination by setting
`tls.mode: passthrough`. In that mode Aurora does not inspect the traffic, and
health checks must use TCP rather than HTTP.
