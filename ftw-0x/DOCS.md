# FTW

FTW plans your battery, car charging and solar around electricity prices and
controls them, here on your Home Assistant.

> **Next steps**
>
> 1. **Start** the app. The first install builds it on your device and takes
>    a few minutes.
> 2. Choose **Open Web UI**.
> 3. On the **Info** tab, turn on **Show in sidebar**, and **Watchdog** so
>    Home Assistant restarts FTW if it stops answering.
> 4. Follow FTW's setup guide: your home, then your devices.
> 5. For Home Assistant entities, add the **Mosquitto broker** app and the
>    **MQTT** integration Home Assistant offers, then restart FTW.
>
> The rest of this page explains each step.

This app runs FTW's stable releases. A stable release is a beta that has run
in real homes for a week; updates come only then. For every new beta, install
**FTW (beta)** instead. The alternative is FTW on a
[separate Linux host](https://github.com/srcfl/ftw/blob/master/docs/native-beta.md)
plus the [MQTT integration](https://github.com/srcfl/ftw/blob/master/docs/ha-integration.md).

## How it works

Supervisor builds this app on your device from FTW's release package for your
CPU (amd64 or aarch64, for example Home Assistant Green). The package's
SHA-256 is pinned in this repository and checked again against the release's
own `.sha256` file. A bad download stops the install.

**Why host network.** FTW uses Home Assistant's own network so it can search
your home network for inverters, meters and chargers, find devices by their
`.local` names, and let OCPP chargers dial in at Home Assistant's address
(port 8887 by default). Host networking also lowers the app's protection
rating in the store.

## 1. Stop any other FTW

Only one FTW may control a home. If you run **FTW (beta)**, or the old 3.x
app, take a backup, turn off **Start on boot** and **Watchdog**, and **Stop**
it. Each app keeps its own settings and history; they do not move over. Stop
FTW on any other computer too.

## 2. Install

1. [![Add the repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fsrcfl%2Fhome-assistant-addons)

   Or open **Settings → Apps → Install app → ⋮ → Repositories** and add
   `https://github.com/srcfl/home-assistant-addons`.
2. Open **FTW** and choose **Install**. The first build downloads packages
   and can take several minutes; wait for it to finish.
3. Turn on **Watchdog**, so Home Assistant restarts FTW when its health check
   fails, then **Start**. **Start on boot** is on already.
4. The **Log** tab should show `FTW starting`. A new install then shows
   `no config found — starting setup wizard`; a home already set up shows `HTTP API ready`.

## 3. Set up

Choose **Open Web UI** inside Home Assistant. A new install opens FTW's setup
guide, which asks for your home and then your devices. HA's administrator
login manages access; no separate FTW password is needed. This also applies
after updating an existing install with a saved FTW password. Your data stays
in place. Turn on **Show in sidebar** on the app's **Info** tab to open FTW
from Home Assistant's sidebar.

The direct LAN web port is closed. Keep a fixed HA address in your router so
your devices keep finding it.

## 4. FTW app and webapp

In FTW, open **Settings → FTW app** and follow
[Pair with one iPhone](https://github.com/srcfl/ftw/blob/master/docs/pairing.md).
Use the pairing link or the QR. Pairing turns on FTW Cloud and accepts its
[terms](https://ftw.energy/privacy). The phone app then connects through FTW
Cloud, so pairing and the phone app need internet; control runs on your Home
Assistant. The phone needs nothing on your home network. The short code with a
box address does not work in this app, since it needs FTW's own web port,
which this app closes.
If you used the webapp with an older FTW, remove it from the home screen and
pair again.

## 5. FTW in Home Assistant

FTW's values show up as Home Assistant entities over MQTT, with nothing to
type. Add the **Mosquitto broker** app and the **MQTT** integration Home
Assistant then offers. If FTW was already running, restart it once. The app
log shows `Home Assistant's MQTT broker is core-mosquitto:1883`. In FTW,
**Settings → Integrations → Enabled** turns this off, and a broker you set
there wins. FTW Core reads the broker from the app from [srcfl/ftw#2096](https://github.com/srcfl/ftw/pull/2096) on;
older FTW needs the broker typed under **Settings → Integrations**.

## Updates and backup

- Updates appear under **Settings → Updates**, once per FTW stable release.
  Take a backup first if you want a way back. `ftw update` does not apply in
  the app.
- Data (settings, history, pairing) lives in the app's `/data` and is in Home
  Assistant backups. The app stops briefly during a backup (cold backup).
- Restore the FTW app from **Settings → System → Backups**. This restores
  both its version and data. Keep other FTW instances stopped during restore.

## Troubleshooting

| Symptom | What to do |
|---|---|
| Not in the store | Check the repository URL; **⋮ → Check for updates**; reload. |
| Install fails | **Settings → System → Logs → Supervisor**. Download/checksum errors: try again later. |
| Web UI does not open | Read the app log. Open it through HA. Ingress port 18099 must be free. |
| FTW app says the box is too old | The phone app may need a newer FTW than the last stable; wait for the next stable or use **FTW (beta)**. |

Report app issues [here](https://github.com/srcfl/home-assistant-addons/issues),
FTW issues [here](https://github.com/srcfl/ftw/issues), or ask in
[Discord](https://discord.gg/UK2ygPBu8N) with the app log.
