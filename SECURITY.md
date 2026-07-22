# Security policy

## Report a flaw

Use a private
[GitHub security advisory](https://github.com/srcfl/home-assistant-addons/security/advisories/new).
Do not put secrets, exploit steps, or private site data in a public issue.

For a flaw in FTW Core or Optimizer, use the
[FTW security advisory form](https://github.com/srcfl/ftw/security/advisories/new).
For a driver flaw, use the
[device-drivers advisory form](https://github.com/srcfl/device-drivers/security/advisories/new).

Include the app version, architecture, Home Assistant OS and Supervisor
versions, impact, steps to reproduce, and any safe fix you know.

## Scope

We support only versions listed in `compatibility.yaml`. Bootstrap entries and
failed or pending pilots are not supported releases.

An image left in the registry by a failed publication workflow is not a
supported beta. A supported beta needs a matching GitHub prerelease, immutable
digest, Cosign signature, SPDX SBOM, and verified GitHub and OCI attestations.

The app grants no Supervisor API, Home Assistant API, Docker API, privileged,
or full-host rights. Host networking is required for Modbus TCP, LAN MQTT, and
device discovery. The image runs Core and Optimizer as an unprivileged user;
the root wrapper only prepares `/data` and the local optimizer socket.

Published beta images and their multi-arch manifest use keyless Cosign
signatures. Each beta also gets an SPDX JSON SBOM and GitHub attestation.
