# FTW (0.x beta)

> **Beta / pilot.** New FTW 0.x on Home Assistant OS. Reviewed FTW beta pins
> arrive as app updates, so expect frequent updates. You choose when to install
> them. The alternative is FTW on a
> [separate Linux host](https://github.com/srcfl/ftw/blob/master/docs/native-beta.md)
> plus the [MQTT integration](https://github.com/srcfl/ftw/blob/master/docs/ha-integration.md).

## How it works

Supervisor builds this app on your device from FTW's release package for your
CPU (amd64 or aarch64, for example Home Assistant Green). The package's
SHA-256 is pinned in this repository and checked again against the release's
own `.sha256` file. A bad download stops the install.

## 1. Stop any other FTW

Only one FTW may control a site. If you run the old **FTW (beta)** app, take a
backup, turn off **Start on boot** and **Watchdog**, and **Stop** it. Its
settings and history do not move over. Stop FTW on any other computer too.

## 2. Install

1. **Settings → Apps → Install app → ⋮ → Repositories**, add
   `https://github.com/srcfl/home-assistant-addons`.
2. Open **FTW (0.x beta)** and choose **Install**. The first build downloads
   packages and can take several minutes; wait for it to finish.
3. Turn on **Start on boot** and **Watchdog**, then **Start**.
4. The **Log** tab should show `FTW starting`. A new install then shows
   `no config found — starting setup wizard`; a configured site shows `HTTP API ready`.

## 3. Set up

Choose **Open web UI**, then **Open FTW**, and follow the setup wizard. Give
Home Assistant a fixed address in your router so devices and apps keep finding
it. FTW opens in a new tab directly on your home network, port 8080; it does
not run inside Home Assistant's frame. Remote access uses a paired FTW client.

To pin FTW to Home Assistant's sidebar, turn on **Show in sidebar** on the
app's **Info** tab. The sidebar entry opens the same page with the
**Open FTW** button.

## 4. FTW app and webapp

In FTW: **Settings → FTW app**, then follow
[Pair with one iPhone](https://github.com/srcfl/ftw/blob/master/docs/pairing.md).
If you used the webapp with an older FTW, remove it from the home screen and
pair again.

## Updates and backup

- Updates appear under **Settings → Updates**. Take a backup first if you want
  a way back. `ftw update` does not apply in the app.
- Data (settings, history, pairing) lives in the app's `/data` and is in Home
  Assistant backups. The app stops briefly during a backup (cold backup).
- Restore the FTW app from **Settings → System → Backups**. This restores
  both its version and data. Keep other FTW instances stopped during restore.

## Troubleshooting

| Symptom | What to do |
|---|---|
| Not in the store | Check the repository URL; **⋮ → Check for updates**; reload. |
| Install fails | **Settings → System → Logs → Supervisor**. Download/checksum errors: try again later. |
| Web UI does not open | Read the app log. Port 8080 must be free. |
| FTW app says the box is too old | You installed the old **FTW (beta)**; install **FTW (0.x beta)**. |

Report app issues [here](https://github.com/srcfl/home-assistant-addons/issues),
FTW issues [here](https://github.com/srcfl/ftw/issues), or ask in
[Discord](https://discord.gg/UK2ygPBu8N) with the app log.
