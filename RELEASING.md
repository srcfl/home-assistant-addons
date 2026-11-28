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
   Older release events cannot lower the pin. The workflow starts CI explicitly
   because PRs opened with `GITHUB_TOKEN` do not start it themselves.
4. The workflow recreates the diff from the public release receipt. Only the
   bot's three pin files may change. It runs all seven Check jobs on the exact
   PR commit, then merges automatically. If main moved, it updates the branch
   and tests again. Failed or skipped checks stop publication.
5. **The merge publishes the app version.** Supervisor builds it on each user's
   device. The workflow explicitly runs Check on main after merging, since a
   `GITHUB_TOKEN` merge does not trigger push workflows. It pushes no image and
   creates no release.

Manual handoff: run **Pin new FTW 0.x release** (`sync-native.yml`) with an
exact published tag, or leave the tag empty to select the newest eligible beta.

App changes merged between pins go under `## Unreleased` at the top of the
app's `CHANGELOG.md`. The next pin turns that heading into its version, so the
changes reach users with the next FTW release.

Every published native beta starts this flow; it does not wait for a daily
schedule. Users see an update after the verified pin merges automatically. Keep HA's **Auto update** off
during the pilot and take a backup before updating. Supervisor owns app updates
and restores; the native launcher's trial and automatic rollback do not apply.
See [qualification](pilot/README.md).

## 0.x stable

The stable app's slug is `ftw`; its name is **FTW**. It lives in `ftw-0x/` and
uses the beta app's recipe: `Dockerfile` (bar the three pin lines),
`run.sh`, `healthcheck.sh`, `mqtt-service.sh` and every manifest setting
except name, slug, url, description and the pins. `validate.py` refuses
drift, so change both apps together. A recipe change reaches stable users
with the next stable pin, since Supervisor rebuilds an app only when its
version moves.

Only a stable tag (`v0.X.Y`, `v0.131.0` or later) moves it; a beta never does.
Until the first one, its manifest is `ftw-0x/unlisted.yaml` with empty pins.
Supervisor reads only `config.yaml`, so the app is not in the store. The
first stable pin writes `ftw-0x/config.yaml` from it and removes
`unlisted.yaml`; that merge lists the app. Do not rename the file by hand.

1. Core promotes a tested beta to `v0.X.Y` with `native-release.yml`.
2. Core sends no event for a stable today. Run
   `gh workflow run sync-native.yml --repo srcfl/home-assistant-addons --ref main -f tag=v0.X.Y`.
3. The workflow opens `bot/pin-ftw-v0.X.Y` and publishes it after Check, as
   for a beta. Its receipt must say `"channel": "stable"`.

The beta app does not take stable releases. Each app keeps its own `/data`,
so moving between them is a new setup.

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
The slug `ftw` was listed once before, as `0.1.0-beta.1` (Core v1.10.0-beta.1),
from 22 July to 18 September 2026. No stable version of it was ever published.
The first 0.x stable pin offers any such install an update to 0.x.

Removing a store entry does not uninstall an existing app or delete its data.
HA may flag the old app as removed from its repository. Keep its backup and
published images for recovery. New installs use
[FTW (beta)](ftw-0x-beta/DOCS.md), or the separate-host route in the README.
