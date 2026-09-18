# Release FTW for Home Assistant

Releases follow FTW. The app version is the FTW Core version without the `v`.

## Normal path (automated)

1. **Sync upstream FTW** (`sync-upstream.yml`) runs hourly and whenever
   `srcfl/ftw` sends `repository_dispatch` `ftw-release` at the end of its
   beta or stable release workflow. It reads FTW's GitHub releases, never the
   event payload, so a dispatch only makes the next check immediate.
2. For the newest FTW beta it verifies the Core image against FTW's
   `ftw-image-digests.json` receipt and the registry, records the current
   signed stable driver manifest, and writes `ftw-beta/config.yaml`,
   `compatibility.yaml` and the changelog. For the newest FTW stable, once the
   pilot is recorded, it reads `ftw-promotion-receipt.json`, finds the app
   beta built from that Core digest, and writes `ftw/config.yaml`.
3. It opens a pull request, runs **Check** on it, merges it when green, and
   dispatches **Auto publish**.
4. **Auto publish** (`auto-publish.yml`) dispatches **Publish beta** for a beta
   version without a tag, and **Promote stable** for a stable version without a
   tag. It also runs hourly as a fallback.
5. **Publish beta** builds both native architectures from the pinned Core
   digest, signs each image and the multi-arch manifest, emits SPDX SBOMs and
   attestations, and creates a prerelease with an immutable release manifest.
6. **Promote stable** re-tags the qualified beta digest as the stable version
   and `stable`, verifies the signature, and creates the release. It has no
   build step and fails if any digest differs.

Run every release workflow only from `main`. Each one stops before registry
login unless `github.ref` is `refs/heads/main` and the checked-out commit
equals `github.sha`.

## Stable gate

Stable promotion needs `qualification.home_assistant_os_supervisor.status:
passed` in `compatibility.yaml`, recorded by a reviewed pull request after the
checks in [pilot/README.md](pilot/README.md). Until then the sync logs that the
stable channel is blocked and the `ftw` app has no `config.yaml`.

## Manual runs

- `gh workflow run sync-upstream.yml` checks upstream now.
- `gh workflow run release-beta.yml -f version=X.Y.Z-beta.N` publishes the
  version in `ftw-beta/config.yaml`; the input must match it.
- `gh workflow run promote-stable.yml -f version=X.Y.Z -f beta_version=X.Y.Z-beta.N -f beta_digest=sha256:…`
  promotes the version in `ftw/config.yaml`; the inputs must match
  `compatibility.yaml`.

## Known limits

- The sync pins only the newest FTW beta. If two betas publish within one sync
  window and FTW later promotes the older one, no app beta exists for it and
  the sync logs `app beta X is not published yet`. Stable then waits for the
  next FTW promotion. The dispatch from FTW makes this rare.
- A partial beta publication cannot be rerun for the same version. Use
  **Finalize partial beta** with the failed run, source commit and digests; it
  never builds or rewrites an image tag. If it fails, treat the candidate as an
  orphan until a separate review approves a recovery.
