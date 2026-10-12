# Recover file ownership after a Supervisor restore

Use this only for an existing FTW app that cannot open its restored data due
to file permissions. Keep the original Home Assistant backup and its key.
Restore the matching old app version. This step does not update Core or move
data into the new FTW line.

Supervisor can copy restored files as root while keeping their private modes,
such as `0600`. The old FTW app runs as uid 100, gid 101. Its launcher sets
directory owners but does not repair owners of files that already exist.

The recovery command below sets owners to 100:101. It preserves file bytes,
modes and internal links, and leaves Core stopped. It refuses external,
broken or cyclic links, hard links and nested mounts before changing owners.
If it refuses the data, keep every copy and inspect the source. Do not remove
the check or create an empty setup.

## Before running the command

1. Complete the Supervisor restore from the original matching backup.
2. In the FTW app page, turn off **Start on boot** and **Watchdog** again: the
   restore may have returned their saved values. Record the restored FTW
   container's image and data mount before stopping it; Supervisor can remove
   the container when it stops the app.
3. If a replacement FTW Core is running, save its full backup and stop it
   before starting the old app. Keep any broker the devices need running.
4. Use an administrator terminal with access to Docker on the Supervisor
   host. Confirm the restored old FTW container and its `/data` mount. Do not use this
   command on another app or on the replacement FTW data.

The example needs Bash, curl and sha256sum on the operator host. The matching
FTW image supplies the recovery container's tools; no image build is needed.

```bash
set -euo pipefail
APP_CONTAINER='REPLACE_WITH_THE_VERIFIED_FTW_CONTAINER_NAME'
IMAGE_ID="$(docker inspect --format '{{.Image}}' "$APP_CONTAINER")"
DATA="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$APP_CONTAINER")"
test -n "$IMAGE_ID"
test -n "$DATA"

# Stop FTW through Supervisor now, with Start on boot and Watchdog off.
# It may retain state "error" after a failed start and remove the container.
# Check Docker itself: the selected old Core must not be running.
test -z "$(docker ps --quiet --filter "name=^/${APP_CONTAINER}$")"

mkdir -m 0700 ftw-owner-recovery
cd ftw-owner-recovery
curl --fail --location --output restore_data_owner.sh \
  https://raw.githubusercontent.com/srcfl/home-assistant-addons/main/scripts/restore_data_owner.sh
printf '%s  %s\n' 'a13a1fb996040da8049f9cd1d58c903bf4121b36e9bcc6a277e6dbcdf763e5df' restore_data_owner.sh | sha256sum --check -
TOOL="$(pwd)/restore_data_owner.sh"

docker run --rm --network none --user 0:0 --workdir / \
  --mount "type=bind,src=$DATA,dst=/data" \
  --mount "type=bind,src=$TOOL,dst=/recovery.sh,readonly" \
  --entrypoint bash "$IMAGE_ID" /recovery.sh
```

Start the original app through Supervisor only after the command succeeds.
Check its exact version, retained settings, driver choices, historical points
and fresh telemetry. Keep Start on boot and Watchdog off until the selected
Core is healthy and every other Core remains stopped. Retain both the old
backup and any replacement Core's backup.

## Evidence and limits

The permission failure appeared after real Supervisor 2026.10.0 full-restore
jobs on a separate official development container, using published FTW
3.8.0-beta.1 and synthetic data. The source archive already had the correct
uid/gid 100/101. Supervisor's restore uses `shutil.copytree`, which keeps
file modes but does not keep file owners.

Linux tests cover private modes and bytes, internal link chains, repeated
recovery, and refusal of external/broken/cyclic links, hard links, a linked
data root and a nested bind mount. These checks do not qualify all Home
Assistant OS or community layouts, entity continuity or physical control.
The old 3.x publication workflows remain retired.
