# FTW (beta) app guide

This app installs the FTW Core image of the newest FTW beta with a small
Supervisor wrapper. Home Assistant Supervisor owns install, update, backup and
rollback; FTW's own updater is not in the image.

## Channels

| App | Follows | Version |
|---|---|---|
| **FTW (beta)** (this app) | every FTW beta `vX.Y.Z-beta.N` | `X.Y.Z-beta.N` |
| **FTW** | every FTW stable `vX.Y.Z` | `X.Y.Z` |

Both apps install the same image, `ghcr.io/srcfl/home-assistant-addons/ftw`,
at different tags. A stable version is the exact beta image FTW promoted,
re-tagged and never rebuilt.

The two apps are separate Home Assistant apps with separate `/data`. To move
from beta to stable, take a backup of this app, install FTW, stop it, and copy
the backup's data into the new app's data directory before starting it.
Supervisor cannot restore one app's backup into another app by itself.

## First start

1. Start FTW (beta).
2. Open its web interface on port 8080.
3. Complete FTW setup.

Until setup writes `/data/config.yaml`, the container health check tests the
setup page. After that file exists, it requires valid JSON from Core's
`/api/status` endpoint.

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

## Update and rollback

Take a Home Assistant backup before each update. If a beta fails, restore the
prior app version and its matching backup, then report the beta in the FTW
repository.

## Support

See the repository [support routes](https://github.com/srcfl/home-assistant-addons/blob/main/SUPPORT.md).
Include the app version, architecture, Home Assistant OS and Supervisor
versions, and relevant logs.
