# Sourceful FTW for Home Assistant

This is the official Home Assistant app repository for
[FTW](https://github.com/srcfl/ftw).

The repository is public, but it is not ready for normal use. A registry image
from an incomplete workflow is not a release. Install only a version that has a
matching GitHub release, signed image, SBOM, and attestation. Stable stays
blocked until the same beta image passes a Home Assistant OS and Supervisor test
for install, boot, data retention, update, rollback, and fallback.

## Install

Do not install a version that lacks a GitHub release and signed image. When the
first beta is published:

1. In Home Assistant, open **Settings → Apps → App store → Repositories**.
2. Add `https://github.com/srcfl/home-assistant-addons`.
3. Install **FTW**.

The app supports `amd64` and `aarch64`. Home Assistant Supervisor downloads a
pre-built image; it does not build FTW on your host.

See [FTW app docs](ftw/DOCS.md), [compatibility](COMPATIBILITY.md), and
[support routes](SUPPORT.md).

## Release rules

FTW app versions are independent from FTW Core and FTW Optimizer versions.
Each release records both upstream versions, their image digests, protocol
features, and test evidence in `compatibility.yaml`.

Beta images use the `beta` channel tag. Stable promotion adds a `stable` tag to
the exact tested beta manifest digest. Stable promotion never rebuilds the
image. FTW's updater is not present; Home Assistant Supervisor owns update and
rollback.

If publication stops after it writes the immutable image, the normal beta
workflow cannot run again for that version. The separate finalize workflow may
complete it only when the failed run, source commit, image digests, signatures,
SBOMs, upstream images, and driver baseline still match. It never builds or
rewrites an image tag. A failed finalize publishes no supported release, but
`gh release create` may leave a hidden draft if an asset upload or network step
fails. The next target check stops when that draft exists. Finalize must not
retry automatically, delete the draft or tag, overwrite assets, or reuse the
candidate. Treat the candidate as an orphan until a separate review approves a
recovery; otherwise use a new beta version. The release manifest keeps the
original image source commit; the OCI attestation also records the reviewed
finalize workflow commit.

## Credit

Erik Arenhill built and maintained the first community FTW add-on. HuggeK's
[FTW PR #620](https://github.com/srcfl/ftw/pull/620) supplied the first
Core-plus-Optimizer package and process wrapper. This repository keeps their
useful work and records the changes in [ATTRIBUTION.md](ATTRIBUTION.md).

Licensed under the [Apache License 2.0](LICENSE).
