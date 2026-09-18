# FTW app guide

## Channels

| App | Follows | Version |
|---|---|---|
| **FTW** (this app) | every FTW stable `vX.Y.Z` | `X.Y.Z` |
| **FTW (beta)** | every FTW beta `vX.Y.Z-beta.N` | `X.Y.Z-beta.N` |

Both apps install the same image, `ghcr.io/srcfl/home-assistant-addons/ftw`,
at different tags. A stable version is the exact beta image FTW promoted,
re-tagged and never rebuilt. The two apps are separate Home Assistant apps with
separate `/data`; moving between them means restoring a backup into the other
app by hand, because Supervisor cannot restore one app's backup into another.

## Before you install

Install only a version that has a GitHub release and signed image. A version in
the source tree alone is not installable.

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

On a normal Home Assistant host, with the device on the same network segment,
this needs nothing turned on. Supervisor points every app at its own DNS server,
and that server answers `.local` names, so a device configured as `zap.local`
resolves like any other name. Verified on a pilot install: a device that had
moved off its configured IP address was still reached by name, while the address
itself returned `no route to host`.

### What this depends on

On the same network segment, there is nothing you have to install and nothing
this app could install for you. A working Home Assistant already has the needed
DNS and host resolver.

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

**A working mDNS path to the device.** This app uses host networking, so it can
use the host's network interfaces. mDNS stays on one network segment by default.
A device on another subnet or VLAN needs an mDNS reflector or repeater between
the networks, and normal network rules must allow traffic to the resolved
address.

### When a name does not resolve

The log says which resolver was asked:

```
lookup zap.local on 172.30.32.3:53: no such host
```

`172.30.32.3` is Home Assistant's DNS service, so seeing it means the request
reached that service. Its mDNS plugin asks `systemd-resolved`; `no such host`
does not prove that the device is absent. It can also mean that the device has
stopped advertising, multicast traffic is blocked or not repeated between
networks, or the host resolver is not working.

If the address is routable, configuring the device by IP is the fallback. It can
break again the next time its DHCP lease moves.

## Data and drivers

Home Assistant keeps `/data` across restarts and updates. It contains FTW's
configuration, SQLite state, history, managed driver cache, and user drivers.

- `/data/drivers` holds user files. The app never replaces them.
- `/data/driver-repository` holds signed managed driver data from the stable
  `srcfl/device-drivers` release channel.
- `/app/drivers` holds the bundled offline recovery set from the pinned Core
  image.

The app uses cold backups. Supervisor stops FTW before it copies `/data`.

## Planner

Core is the only process. It bundles the compiled Energyplan worker and falls
back to its Go planner when the worker is unavailable; neither case makes the
app unready. There is no separate optimizer container or socket.

## Update and rollback

Home Assistant Supervisor owns app updates and rollback. FTW self-update is
off and the FTW updater is not in this image.

The FTW web interface reports the single bundled FTW version under
Settings → System instead of per-container component versions with update
buttons.

Before each update, take a Home Assistant backup. If an update fails, restore
the prior app version and its matching backup. A stable version is the exact
beta image FTW promoted, re-tagged and never rebuilt.

## Support

See the repository [support routes](../SUPPORT.md). Include the app version,
architecture, Home Assistant OS and Supervisor versions, and relevant logs.
