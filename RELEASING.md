# Home Assistant app releases

## Current 0.x beta

Sourceful maintains this repository. Fredrik owns FTW's product direction.
The app slug is `ftw-0x-beta`; its name is **FTW (0.x beta)**.
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

Manual handoff: run **Pin new FTW 0.x beta** (`sync-native.yml`) with an exact
published tag, or leave the tag empty to select the newest eligible beta.

Every published native beta starts this flow; it does not wait for a daily
schedule. Users see an update after the verified pin merges automatically. Keep HA's **Auto update** off
during the pilot and take a backup before updating. Supervisor owns app updates
and restores; the native launcher's trial and automatic rollback do not apply.
There is no stable 0.x app yet. See [qualification](pilot/README.md).

An app-only change may add `.ha.N` to the pinned Core beta version. It keeps
that Core package and receipt. A same-tag sync preserves the app revision;
the next Core beta replaces it with that beta's version. Do not activate an
app feature before the pinned Core package supports it.

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
The old `ftw` stable app has no manifest and was never published.

Removing a store entry does not uninstall an existing app or delete its data.
HA may flag the old app as removed from its repository. Keep its backup and
published images for recovery. New installs use
[FTW (0.x beta)](ftw-0x-beta/DOCS.md), or the separate-host route in the README.
