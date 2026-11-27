---
title: Installing Aurora Deploy
url: https://docs.aurora.invalid/install
---

# Installing Aurora Deploy

Aurora Deploy is fictional; the steps below exist so the demo corpus has a
plausible installation chapter.

## Requirements

- A Linux or macOS workstation with `aurora` 2.4 or newer on the `PATH`.
- Network access to the Aurora registry mirror during installation only.
- At least 8 GiB of memory on the machine that runs the local control plane.

## Steps

1. Download the `aurora` archive for your platform and unpack it under
   `/opt/aurora`.
2. Run `aurora init --home /opt/aurora --accept-license`. The command writes
   the configuration file `aurora.yaml` and creates the local state directory.
3. Start the control plane with `aurora serve`. It listens on port 7443 by
   default and refuses to start if the port is already bound.
4. Verify the installation with `aurora doctor` (see the CLI reference).
5. Register the first project with `aurora project create --name demo`.

## Offline installs

Pass `--offline` to `aurora init` to skip the registry mirror check. Offline
installs cannot pull blueprint images until the mirror is reachable again.
