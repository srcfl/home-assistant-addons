# Home Assistant app releases

## Current 0.x beta

Sourceful maintains this repository. Fredrik owns FTW's product direction.
The app slug is `ftw-0x-beta`; its name is **FTW (0.x beta)**.

1. Core publishes a native 0.x beta with both Linux packages, their checksums
   and `ftw-native-release.json`.
2. Core's `native-release.yml` sends `ftw-native-release` to this repository
   with `HA_ADDON_DISPATCH_TOKEN`. If the secret is absent, it reports that
   the pin must move manually. A failed handoff can be retried without a new release.
3. `sync-native.yml` checks the receipt and checksum files, moves the pins in
   `config.yaml` and `Dockerfile`, adds a changelog entry and opens a PR.
   Older release events cannot lower the pin. The workflow starts CI explicitly
   because PRs opened with `GITHUB_TOKEN` do not start it themselves.
4. A maintainer reviews the PR and its checks, then merges it. **That merge
   publishes the app version.** Supervisor builds it on each user's device.
   This workflow does not push an image or create a release.

Manual handoff: run **Pin new FTW 0.x beta** (`sync-native.yml`) with an exact
published tag, or leave the tag empty to select the newest eligible beta.

Every new beta may propose a pin PR. Users see an update after a maintainer
merges it; there is no daily automatic merge. Keep HA's **Auto update** off
during the pilot and take a backup before updating. Supervisor owns app updates
and restores; the native launcher's trial and automatic rollback do not apply.
There is no stable 0.x app yet. See [qualification](pilot/README.md).

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

Keep the old apps and their data available for recovery. Do not remove them
as part of the 0.x beta launch. New installs use
[FTW (0.x beta)](ftw-0x-beta/DOCS.md), or the separate-host route in the README.
