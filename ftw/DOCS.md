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

## Devices named `zap.local`

FTW can be pointed at a device by its `.local` name instead of its IP address,
which matters because a DHCP lease can move a device and silently break a
connection bound to a raw IP.

FTW resolves those names itself, by asking the local network directly. It does
not use the operating system's resolver and does not need any Home Assistant
setting turned on. What it does need is the host networking this app already
uses — that is what puts it on the same network segment as the device.

Two consequences worth knowing:

- On Home Assistant this always uses the direct path. Elsewhere FTW can hand
  `.local` lookups to a host `avahi-daemon` over a Unix socket, but Supervisor
  gives an add-on no way to bind an arbitrary host path, so that option does not
  exist here. Nothing is lost — the direct path needs no host software.
- A failed lookup is logged as `mDNS resolution failed`. If you see it, the
  device is usually off, asleep, or on a different subnet or VLAN than Home
  Assistant. Configuring that device by IP is the workaround.

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

Before each update, take a Home Assistant backup. If a beta fails, restore the
prior app version and its matching backup. Stable promotion reuses the exact
beta manifest digest that passed the Home Assistant OS and Supervisor pilot.

## Support

See the repository [support routes](../SUPPORT.md). Include the app version,
architecture, Home Assistant OS and Supervisor versions, and relevant logs.
