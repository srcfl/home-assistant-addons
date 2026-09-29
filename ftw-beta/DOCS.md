# Existing FTW app: operation and recovery

**This is the retired release line. 2.x and 3.x receive no more updates.**
The app does not follow new 0.x. Do not install 3.x beta or change app channels
to get current FTW. No new-line app has shipped; stable remains unpublished.

Follow [Install and update FTW](https://github.com/srcfl/ftw/blob/master/docs/native-beta.md)
to use a separate new native or Docker setup now. Keep a Home Assistant backup
and old data. Stop the app's Core, Start on boot and Watchdog before the new
host controls the equipment, then check again after reboot. Guided migration
of settings and history is not ready; do not copy the app's data into new Core.
The MQTT integration can connect Home Assistant to the new host.

The following sections describe an already installed app. Supervisor owns its
backup and restore; FTW self-update is off. Its web page uses port 8080.

## Data and drivers

Home Assistant keeps `/data` across restarts and updates. It contains FTW's
configuration, state database, history, managed driver cache, and user drivers.

- `/data/drivers` holds user files. The app never replaces them.
- `/data/driver-repository` holds signed managed driver data from the stable
  `srcfl/device-drivers` release channel.
- `/app/drivers` holds the bundled offline recovery set from the pinned Core
  image.

The app uses cold backups. Supervisor stops FTW before it copies `/data`.

## Devices named `zap.local`

Supervisor points every app at its own DNS service, which answers `.local`
names through the host resolver, so a device configured as `zap.local` resolves
without extra setup on Home Assistant OS. See the
[full FTW app guide](https://github.com/srcfl/home-assistant-addons/blob/main/ftw/DOCS.md)
for what that depends on and how to read a failed lookup.

## Recovery

Take a Home Assistant backup before any recovery. Restore only the original
compatible app version with its matching backup. Supervisor owns recovery;
FTW's own updater is not present. There are no new 2.x or 3.x updates, and an
old update notice is not a path to new 0.x.

## Support

See the repository [support routes](https://github.com/srcfl/home-assistant-addons/blob/main/SUPPORT.md).
Include the app version, architecture, Home Assistant OS and Supervisor
versions, and relevant logs.
