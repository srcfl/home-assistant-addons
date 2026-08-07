# FTW app guide

## Before you install

Install only a beta or stable version that has a GitHub release and signed
image. A version in the source tree alone is not installable.

The app supports Home Assistant OS and Supervised installs on `amd64` and
`aarch64`. It uses host networking so FTW can reach devices on the local
network. The web interface listens on port 8080.

## First start

1. Start FTW.
2. Open its web interface.
3. Complete FTW setup.

Until setup writes `/data/config.yaml`, the container health check tests the
setup page. After that file exists, it requires valid JSON from Core's
`/api/status` endpoint after Core opens its state.

## Data and drivers

Home Assistant keeps `/data` across restarts and updates. It contains FTW's
configuration, SQLite state, history, managed driver cache, and user drivers.

- `/data/drivers` holds user files. The app never replaces them.
- `/data/driver-repository` holds signed managed driver data from the stable
  `srcfl/device-drivers` release channel.
- `/app/drivers` holds the bundled offline recovery set from the pinned Core
  image.

The app uses cold backups. Supervisor stops FTW before it copies `/data`.

## Optimizer fallback

Core is the main process. The Python Optimizer uses only the Unix socket at
`/run/ftw-optimizer/optimizer.sock`. A socket, handshake, or solve error makes
Core use its Go planner. It does not make the app unready.

The app restarts the Optimizer after failure. The delay grows to 60 seconds and
then stays capped, so the worker can return without a container restart.

## Update and rollback

Home Assistant Supervisor owns app updates and rollback. FTW self-update is
off and the FTW updater is not in this image.

Because Core and the Optimizer ship together in one image, the FTW web
interface reports the single bundled FTW version under Settings → System
instead of per-container component versions with update buttons.

Before each update, take a Home Assistant backup. If a beta fails, restore the
prior app version and its matching backup. Stable promotion reuses the exact
beta manifest digest that passed the Home Assistant OS and Supervisor pilot.

## Support

See the repository [support routes](../SUPPORT.md). Include the app version,
architecture, Home Assistant OS and Supervisor versions, and relevant logs.
