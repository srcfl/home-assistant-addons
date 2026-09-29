# Sourceful FTW for Home Assistant

**FTW 2.x and 3.x will receive no further updates. All new releases use the
new 0.x line. Do not install this repository's 3.x beta to get current FTW.**

The existing app is on the retired 3.x line. It does not follow new 0.x
releases, and no new-line Home Assistant app has shipped. The stable app has
not been qualified or published.

## Switch to current FTW

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
