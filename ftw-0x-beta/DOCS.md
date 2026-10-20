# FTW (0.x beta)

## What this is

The new FTW 0.x line, packaged for Home Assistant OS (amd64 and aarch64, for
example Home Assistant Green). Supervisor builds the app on your device from
FTW's published release package; the package's SHA-256 is pinned in this
repository and checked again against the release's own `.sha256` file.

## Before you install

- Only one FTW may control a site. Stop the old **FTW (beta)** app (and turn
  off its Start on boot and Watchdog) or any separate FTW host first.
- Data is new and separate. Settings and history from the old 3.x app do not
  move over.

## Use

Open the web UI (port 8080) and follow `/setup`. Data lives in the app's
`/data` and is included in Home Assistant backups (the app stops for backup).

Updates arrive as normal Home Assistant app updates. `ftw update` does not
apply inside the app.
