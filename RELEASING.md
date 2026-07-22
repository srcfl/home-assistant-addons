# Release FTW for Home Assistant

The add-on has its own SemVer. Core, Optimizer, and drivers keep their own
release lines. Do not infer one version from another.

## First beta

1. Wait for the Core and Optimizer owners to send exact versions, commits, and
   multi-arch image digests from the passed pilot.
2. Set an add-on version such as `0.1.0-beta.1` in `ftw/config.yaml` and
   `compatibility.yaml`.
3. Record each upstream version, commit, digest, protocol, and feature. Set
   `update_owner` to `home_assistant_supervisor`. Do not add an updater.
4. Set the add-on manifest digest to `__PUBLISHED_BY_BETA_WORKFLOW__` and record
   the upstream gate as passed with a link to its evidence.
5. Merge those pins after review and run **Publish beta** for the same version.
6. Copy the workflow's manifest digest into `compatibility.yaml`. Keep the
   channel at beta and publish that record before the Home Assistant pilot.

The beta workflow builds both native architectures, signs each image and the
multi-arch manifest, emits an SPDX JSON SBOM, adds an SBOM attestation, and
creates a prerelease with an immutable release manifest.

## Home Assistant pilot

Run the steps in [pilot/README.md](pilot/README.md) on real Home Assistant OS
and Supervisor hardware. Stable stays blocked until all steps pass.

## Stable promotion

1. Change only store and release metadata for the stable add-on version. Remove
   `stage: experimental` so Home Assistant applies its stable default.
2. Record the passed pilot and its evidence in `compatibility.yaml`.
3. Set `promoted_from_beta` to the tested beta channel, version, digest, and
   source commit. Set the stable add-on manifest digest to that same digest.
4. Merge the reviewed metadata change.
5. Run **Promote stable** with the stable version, beta version, and beta
   digest.

The stable workflow creates new tags for the existing beta digest. It has no
build step and fails if any digest differs.
