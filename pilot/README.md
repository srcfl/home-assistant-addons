# Home Assistant qualification

## FTW 0.x beta

The [app PR](https://github.com/srcfl/home-assistant-addons/pull/21) records
tests on a fresh aarch64 VM with Home Assistant OS 18.3 and Supervisor/Core
2026.10.2. VM results do not qualify the Green board or any energy equipment.

For the physical Green pilot:

1. Back up and stop the old FTW, including Start on boot and Watchdog. Confirm
   it stays stopped after a host restart.
2. Add the repository URL and install **FTW (0.x beta)**. Keep Auto update off.
   Check setup, the direct web UI and restart through both FTW and Home Assistant.
3. Connect the site meter and devices. Verify fresh measurements, the site limits,
   planner operation and physical response before claiming control works.
4. Pair the intended FTW phone/web client. Check local operation when the
   internet connection is unavailable.
5. Take a Home Assistant backup. Restore the FTW app and check its version,
   settings, history, keys and user drivers. Keep other FTW instances stopped.
6. Update to the next reviewed pin through Home Assistant and verify that the
   same site data and pairing remain. Check Watchdog recovery and a full host restart.

Record HA OS, Supervisor, FTW and driver versions, board and device models,
firmware, tested commands and results in a PR. Link the evidence from
`COMPATIBILITY.md`. Do not mark the old 3.x qualification record as passed.

## Historical 3.x pilot

The 3.x app is retired. 2.x and 3.x receive no further updates, and no stable
app passed this pilot. Do not install 3.x beta or run the old promotion path
as a way to get current FTW.

Use [Install and update FTW](https://github.com/srcfl/ftw/blob/master/docs/native-beta.md)
for the new 0.x line on a separate Linux host.

The [original pilot checklist](https://github.com/srcfl/home-assistant-addons/blob/82172cec84d7d756e35ed40da48e82c59ef5a6f1/pilot/README.md)
records the checks planned for the old packaging: boot, data retention,
update, rollback and planner fallback on real Home Assistant OS hardware.
It remains a historical reference for old compatibility records, not a
current release procedure. Any future app for the new line needs its own
packaging, qualification and release decision.
