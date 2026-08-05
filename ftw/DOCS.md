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

On Home Assistant this needs nothing turned on. Supervisor already points every
app at its own DNS server, and that server answers `.local` names, so a device
configured as `zap.local` resolves like any other name. Verified on a pilot
install: a device that had moved off its configured IP address was still reached
by name, while the address itself returned `no route to host`.

### What this depends on

Nothing you have to install, and nothing this app could install for you. The
three requirements are all things a working Home Assistant already has.

**Home Assistant's own DNS service.** Supervisor runs five built-in
services — CLI, DNS, audio, observer and multicast — and starts them itself on
every system. They are not add-ons: they cannot be installed, removed or
requested, and an app has no way to declare a dependency on one. If the DNS
service ever fails to start, Supervisor raises it as a repairable system issue
of its own accord. The `.local` answer comes from that service.

**`systemd-resolved` on the host.** Home Assistant's DNS service answers
`.local` by asking the host's resolver, so the host has to have one.

- **Home Assistant OS** — always present. Nothing to do.
- **Home Assistant Supervised** — present if you followed the documented
  installation, whose first step converts the host to NetworkManager and
  `systemd-resolved`. On a host where that step was skipped, `.local` names will
  not resolve and devices must be configured by IP address.

**The device on the same network segment.** This app already uses host
networking, which is what puts it there. A device on another subnet or VLAN
cannot be reached by name no matter what resolves it.

### When a name does not resolve

The log says which resolver was asked:

```
lookup zap.local on 172.30.32.3:53: no such host
```

`172.30.32.3` is Home Assistant's DNS service, so seeing it means the request
reached the right place and the answer was genuinely "no such name" — the device
is off, asleep, or on a different network. A different address there, or a
timeout instead of `no such host`, points at the host resolver instead.

Configuring the device by IP address is the workaround, at the cost of breaking
again the next time its DHCP lease moves.

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
