# Changelog

## 0.1.0-beta.1

- Pin the tested Core and Optimizer beta images.
- Record the tested stable driver baseline while keeping driver updates separate.
- Keep the add-on image unpublished until release input review passes.
- Identify the image to FTW as the Home Assistant bundle (`FTW_BUNDLE`,
  `FTW_BUNDLE_VERSION`), so the FTW web UI can show the single bundled FTW
  version instead of a per-container Core/Optimizer breakdown.
- Pass the pinned Core release tag as `FTW_IMAGE_TAG`, so Core reports the
  exact upstream image version for both beta and stable pins.
- Accept Core's base-version OCI label while still binding the exact release
  tag, image digest, and source revision.
- Let Supervisor supply the installed add-on version, so stable promotion
  replaces the image's beta fallback without rebuilding it.

## 0.0.0-dev

- Add the repository bootstrap, runtime contract, checks, and release gates.
- Do not publish an image for this version.
