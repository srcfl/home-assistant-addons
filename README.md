# FTW for Home Assistant

FTW plans your battery, car charging and solar around electricity prices and
controls them. The **FTW (beta)** app runs FTW on Home Assistant OS, for
example on a Home Assistant Green (aarch64) or an amd64 machine. Control runs
on your Home Assistant, not in a cloud.

[![Add the repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fsrcfl%2Fhome-assistant-addons)

Ran FTW 2.x or 3.x before? Read
[Ran an older FTW before?](#ran-an-older-ftw-before) first.

1. Select the button to add this repository to Home Assistant. Or open
   **Settings → Apps → Install app → ⋮ → Repositories** and add
   `https://github.com/srcfl/home-assistant-addons`.
2. Install **FTW (beta)**, version 0.x, and choose **Start**. The first
   install builds the app on your device and takes a few minutes.
3. Choose **Open Web UI** and follow FTW's setup guide. Turn on **Show in
   sidebar** on the app's **Info** tab to open FTW from Home Assistant's
   sidebar.

Step by step: [ftw-0x-beta/DOCS.md](ftw-0x-beta/DOCS.md), also in FTW's docs
([English](https://github.com/srcfl/ftw/blob/master/docs/home-assistant-app.md),
[svenska](https://github.com/srcfl/ftw/blob/master/docs/setup-guide/home-assistant-sv.md)).

FTW (beta) is a beta. Home Assistant builds it on your device from FTW's
published release package and checks the pinned SHA-256; no registry image is
involved. A stable app, **FTW**, joins the store with FTW's first 0.x stable
release.

## FTW on another computer

FTW also runs on any 64-bit Linux computer with systemd, for example a
Raspberry Pi 3 or newer with Raspberry Pi OS Lite (64-bit). Follow
[Install and update FTW](https://github.com/srcfl/ftw/blob/master/docs/native-beta.md)
([svenska](https://github.com/srcfl/ftw/blob/master/docs/setup-guide/update-sv.md)).
Home Assistant can still show FTW's values through the
[MQTT integration](https://github.com/srcfl/ftw/blob/master/docs/ha-integration.md).
Keep a broker that the devices need running.

## Ran an older FTW before?

**FTW 2.x and 3.x will receive no further updates. All new releases use the
new 0.x line. Do not install this repository's old 3.x beta to get current FTW.**

The retired 3.x apps, one of them also named FTW (beta), are no longer listed
for new installs. Existing installations and their data stay on the device.
Keep a Home Assistant backup and the old app's data before moving to the new
app. The new app starts with a new setup and separate data; guided transfer of
old settings and history is not ready. Only one FTW may control a home: stop
the old app and turn off its **Start on boot** and **Watchdog** before new FTW
controls the same equipment, and check that it stays stopped after a reboot.

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
