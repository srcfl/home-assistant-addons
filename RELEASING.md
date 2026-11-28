# Home Assistant app releases

## Current 0.x beta

Sourceful maintains this repository. Fredrik owns FTW's product direction.
The app slug is `ftw-0x-beta`; its name is **FTW (beta)**.
Home Assistant has no `beta` stage. Keep the beta name and version, and omit
`stage` so the store does not add an Experimental flag. This does not promote
FTW to stable.
An already installed app keeps its old metadata until its next update or
rebuild. Reloading the store applies the new store listing; no reinstall is
needed.

1. Core publishes a native 0.x beta with both Linux packages, their checksums
   and `ftw-native-release.json`.
2. Core's `native-release.yml` sends `ftw-native-release` to this repository
   with `HA_ADDON_DISPATCH_TOKEN`. If the secret is absent, it reports that
   the pin must move manually. A failed handoff can be retried without a new release.
3. `sync-native.yml` checks the receipt and checksum files, moves the pins in
   `config.yaml` and `Dockerfile`, adds a changelog entry and opens a PR.
   Older release events cannot lower the pin. A pin also writes the `image:`
   line if the manifest lacks it, as the beta app's did while Supervisor
   built it on the device. For any release after `LAST_BUILT_ON_DEVICE` in
   `scripts/native_pin.py`, `validate.py` refuses a manifest without it, so
   a hand edit cannot quietly return to on-device builds.
4. Trusted code from main recreates the diff from the public release receipt.
   Only the bot's three pin files may change. Nothing is built before this
   check passes.
5. **Image.** One job per CPU, on a native runner (`ubuntu-24.04`,
   `ubuntu-24.04-arm`), builds the PR commit's `Dockerfile`. The build
   downloads the pinned package and checks it against the pin and the
   release's `.sha256` file, as on the device before. The job runs
   `scripts/smoke_native.sh` on the image, pushes it to
   `ghcr.io/srcfl/home-assistant-addons/{arch}-ftw-0x:<version>` and signs the
   pushed digest with keyless Cosign. It never pushes to a tag that exists.
6. The workflow runs all seven Check jobs on the exact PR commit, and starts
   them itself because PRs opened with `GITHUB_TOKEN` do not. If main moved,
   it updates the branch and tests again. Then, without a registry login, it
   checks that both images can be pulled, carry the version and the recipe of
   the commit it merges, and bear the signature of `sync-native.yml` on
   `main`. Only then does it merge. A failed or skipped check, a missing or
   private image, or a missing signature stops publication.
7. **The merge publishes the app version.** Supervisor pulls the image for the
   user's CPU. The workflow then runs Check on main, since a `GITHUB_TOKEN`
   merge does not trigger push workflows. On main, and once a day, Check
   verifies the images of the pinned versions again. It creates no git tag
   or release.

Manual handoff: run **Pin new FTW 0.x release** (`sync-native.yml`) on `main`
with an exact published tag, or leave the tag empty to select the newest
eligible beta. A run from another branch signs as that branch, so its pin
cannot publish.

App changes merged between pins go under `## Unreleased` at the top of the
app's `CHANGELOG.md`. The next pin turns that heading into its version, so the
changes reach users with the next FTW release.

Every published native beta starts this flow; it does not wait for a daily
schedule. Users see an update after the verified pin merges automatically. Keep HA's **Auto update** off
during the pilot and take a backup before updating. Supervisor owns app updates
and restores; the native launcher's trial and automatic rollback do not apply.
See [qualification](pilot/README.md).

### Images

- One image per FTW release and CPU, tagged with the app version and pushed
  once. Both apps pull the same image for the same release, since
  `validate.py` keeps their recipes equal.
- The `com.sourceful.ftw.recipe` label is a digest of `Dockerfile`, `run.sh`,
  `healthcheck.sh` and `mqtt-service.sh` (`scripts/native_image.py`). An app
  change merged between pins reaches users with the next pin, the first image
  built with it.
- Signing is keyless Cosign: GitHub's OIDC token for `sync-native.yml` on
  `main` gets a short-lived certificate, and the signature goes to the public
  Sigstore log. No one holds a signing key. Home Assistant's own builder and
  the retired 3.x images sign the same way. Supervisor checks no signature;
  the pin flow and Check on main do. Every workflow installs cosign v3.0.6;
  check one by hand with the same release:

  ```sh
  cosign version   # v3.0.6
  cosign verify \
    --certificate-identity https://github.com/srcfl/home-assistant-addons/.github/workflows/sync-native.yml@refs/heads/main \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com \
    ghcr.io/srcfl/home-assistant-addons/aarch64-ftw-0x:<version>
  ```

- Never delete, retag or overwrite the image of a version that main pins.
  Installs, updates and restores pull it by that tag.
- `docker buildx build --platform linux/arm64 --build-arg BUILD_ARCH=aarch64 --build-arg BUILD_VERSION=<version> ftw-0x-beta`
  builds the same app on your own machine (`linux/amd64` and `amd64` for the
  other CPU). To try a recipe change in Home Assistant, copy the app folder
  to `/addons` and delete its `image:` line; Supervisor then builds the
  `Dockerfile` on the device.

**Set up once.** The first image job creates the packages `amd64-ftw-0x` and
`aarch64-ftw-0x` under srcfl, linked to this repository. GitHub may create
them private; the publish step then stops with "cannot be pulled without a
login". In each package's settings, change its visibility to **Public** and
check that **Manage Actions access** gives this repository the **Write** role.
Then re-run the failed job; the pushed images stay. No secret is needed: the
image job asks for `packages: write` and `id-token: write` on `GITHUB_TOKEN`.

**When the image step stops.** Re-run the pin workflow. The image job never
pushes a tag twice. If an earlier run pushed but failed to sign, the re-run
signs that digest, but only when its labels show this version, recipe and
pin commit (`native_image.py resume`). Publication then checks the image as
always. A tag it still refuses (built from another commit, or main changed
the recipe while the pin waited) never reached users, since main does not
pin it. Delete that package version on GitHub, then re-run.

## 0.x stable

The stable app's slug is `ftw-0x`; its name is **FTW**. It lives in `ftw-0x/` and
uses the beta app's recipe: `Dockerfile` (bar the three pin lines),
`run.sh`, `healthcheck.sh`, `mqtt-service.sh` and every manifest setting
except name, slug, url, description and the pins. `validate.py` refuses
drift, so change both apps together. A recipe change reaches stable users
with the next stable pin, since each version's image is built once, at its
pin. `unlisted.yaml` already names the image, so the first stable pin lists
the app with it and runs the same image flow as a beta.

Only a stable tag (`v0.X.Y`, `v0.131.0` or later) moves it; a beta never does.
The beta app follows Core's beta channel, which takes the highest release: a
stable moves it too when the stable outranks its beta pin (`v0.X.Y` is above
every `v0.X.Y-beta.N` and below `v0.X.(Y+1)-beta.1`). One pin PR carries
every app a release moves.
Until the first one, its manifest is `ftw-0x/unlisted.yaml` with empty pins.
Supervisor reads only `config.yaml`, so the app is not in the store. The
first stable pin writes `ftw-0x/config.yaml` from it and removes
`unlisted.yaml`; that merge lists the app. Do not rename the file by hand.

1. Core promotes a tested beta to `v0.X.Y` with `native-release.yml`.
2. Core sends `ftw-native-release` for the stable as for a beta
   ([srcfl/ftw#2101](https://github.com/srcfl/ftw/pull/2101)). Without that event, run
   `gh workflow run sync-native.yml --repo srcfl/home-assistant-addons --ref main -f tag=v0.X.Y`.
3. The workflow opens `bot/pin-ftw-0x-v0.X.Y`, builds and signs the image, and
   publishes it after Check, as for a beta. Its receipt must say
   `"channel": "stable"`. A stable that also moves the beta app builds one
   image for both.

Each app keeps its own `/data`, so moving between them is a new setup.

## Retired 2.x and 3.x path

2.x and 3.x receive no further releases. Do not run the old sync, publish,
promotion or finalizer workflows to create another old-line app release.
All new FTW releases use the new 0.x packages. This app does not consume
those packages and must not claim to follow every new beta.

Scheduled, push and upstream-event triggers are removed from the old sync and
auto-publish workflows. Current manual entry points fail before checkout, pin
PRs or registry writes. Do not dispatch historical workflow revisions.

The old workflow code and compatibility records remain for audit and
recovery. Their presence does not authorize publication. The
[previous release procedure](https://github.com/srcfl/home-assistant-addons/blob/82172cec84d7d756e35ed40da48e82c59ef5a6f1/RELEASING.md)
describes that historical pipeline; it is not the current release policy.

The old apps are no longer listed in the store. `ftw-beta/retired.yaml` keeps
the last manifest for recovery; do not rename it to `config.yaml`, `config.yml`
or `config.json`. Supervisor would list it again, even in a nested folder.
The slug `ftw` was listed once, as `0.1.0-beta.1` (Core v1.10.0-beta.1), from
22 July to 18 September 2026. An install may still hold it with that data, and
a listed app with the same slug would offer it an update. So `ftw` and
`ftw-beta` stay retired; `validate.py` refuses any manifest that uses them.

Removing a store entry does not uninstall an existing app or delete its data.
HA may flag the old app as removed from its repository. Keep its backup and
published images for recovery. New installs use
[FTW (beta)](ftw-0x-beta/DOCS.md), or the separate-host route in the README.
