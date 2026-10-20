# Sourceful FTW for Home Assistant

**FTW 2.x and 3.x will receive no further updates. All new releases use the
new 0.x line. Do not install this repository's old 3.x beta to get current FTW.**

## New: FTW (0.x beta) — pilot

**FTW (0.x beta)** runs new FTW 0.x directly on Home Assistant OS, for
example a Home Assistant Green (aarch64) or an amd64 machine. It is a beta
for a first pilot. Home Assistant builds it on your device
from FTW's published release package and checks the pinned SHA-256; no
registry image is involved.

Step by step for beginners:
[ftw-0x-beta/DOCS.md](ftw-0x-beta/DOCS.md), also in FTW's docs
([English](https://github.com/srcfl/ftw/blob/master/docs/home-assistant-app.md),
[svenska](https://github.com/srcfl/ftw/blob/master/docs/setup-guide/home-assistant-sv.md)).
Open **Settings → Apps → Install app → ⋮ → Repositories**, add
`https://github.com/srcfl/home-assistant-addons`, install **FTW (0.x beta)**,
start it and choose **Open web UI**.

The app store offers only **FTW (0.x beta)**. The retired 3.x apps are no
longer listed for new installs. Existing installations and their data stay
on the device; keep a backup before moving to the new app.

## Alternative: FTW on a separate Linux host

Follow [Install and update FTW](https://github.com/srcfl/ftw/blob/master/docs/native-beta.md)
([Svenska](https://github.com/srcfl/ftw/blob/master/docs/setup-guide/update-sv.md)).
Run the new native or Docker package on another 64-bit Linux host. You can
set up the site now with separate data; guided transfer of old settings and
history is not ready. Keep a Home Assistant backup and the old app's data.
Stop old Core, Start on boot and Watchdog before new FTW controls the same
equipment, and verify that it stays stopped after reboot.

Home Assistant can still use the
[MQTT integration](https://github.com/srcfl/ftw/blob/master/docs/ha-integration.md)
with FTW on that separate host. Keep a broker that the devices need running.

## Existing installations and recovery

Supervisor owns the old app's stop, backup and restore operations; FTW's
updater is not in the image. A source version or registry image alone is not
a release. Use the original matching release and backup for recovery, never
an old `beta` or `latest` alias as a way to move to new 0.x.

See [the existing-app guide](ftw-beta/DOCS.md),
[compatibility records](COMPATIBILITY.md), [retired release tooling](RELEASING.md)
and [support routes](SUPPORT.md). Old images and records describe recovery
material, not a recommendation for a new install.

## Credit

Erik Arenhill built and maintained the first community FTW add-on. HuggeK's
[FTW PR #620](https://github.com/srcfl/ftw/pull/620) supplied the first
Core-plus-Optimizer package and process wrapper. This repository keeps their
useful work and records the changes in [ATTRIBUTION.md](ATTRIBUTION.md).

Licensed under the [Apache License 2.0](LICENSE).
