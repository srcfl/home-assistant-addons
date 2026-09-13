# Sourceful FTW for Home Assistant

This is the official Home Assistant app repository for
[FTW](https://github.com/srcfl/ftw).

| App | Slug | Follows | Version |
|---|---|---|---|
| **FTW (beta)** | `ftw-beta` | every FTW beta `vX.Y.Z-beta.N` | `X.Y.Z-beta.N` |
| **FTW** | `ftw` | every FTW stable `vX.Y.Z` | `X.Y.Z` |

Both apps install `ghcr.io/srcfl/home-assistant-addons/ftw:<version>`: the
pinned FTW Core image plus a small Supervisor wrapper. Core bundles the
Energyplan worker and its Go planner fallback, so the app has one process and
no separate optimizer. A stable version is the beta image FTW promoted,
re-tagged and never rebuilt. FTW's updater is not present; Home Assistant
Supervisor owns update and rollback.

## Install

1. In Home Assistant, open **Settings → Apps → App store → Repositories**.
2. Add `https://github.com/srcfl/home-assistant-addons`.
3. Install **FTW (beta)** to follow betas, or **FTW** for stable once it is
   published.

The apps support `amd64` and `aarch64`. Supervisor downloads a pre-built,
signed image; it does not build FTW on your host. Install only a version that
has a matching GitHub release in this repository; an image left in the
registry by a failed workflow is not a release.

See the [app guide](ftw/DOCS.md), [compatibility](COMPATIBILITY.md),
[releasing](RELEASING.md) and [support routes](SUPPORT.md).

## Release rules

Releases follow FTW automatically: the sync workflow pins each new FTW beta
into `ftw-beta` and, once a Home Assistant OS and Supervisor pilot is recorded,
promotes the matching beta into `ftw` when FTW promotes. Every pin is verified
against FTW's release receipt and the registry before anything is built.

Stable stays blocked until the pilot in [pilot/README.md](pilot/README.md) is
recorded in `compatibility.yaml`.

## Credit

Erik Arenhill built and maintained the first community FTW add-on. HuggeK's
[FTW PR #620](https://github.com/srcfl/ftw/pull/620) supplied the first
Core-plus-Optimizer package and process wrapper. This repository keeps their
useful work and records the changes in [ATTRIBUTION.md](ATTRIBUTION.md).

Licensed under the [Apache License 2.0](LICENSE).
