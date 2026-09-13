# Home Assistant OS and Supervisor pilot

The pilot qualifies the packaging once: install, boot, data retention, update,
rollback and Core's planner fallback on real Home Assistant OS and Supervisor
hardware. It gates the stable app. Beta versions publish without it; stable
promotion refuses to run until `compatibility.yaml` records a passed pilot.

Run the checks on the newest **FTW (beta)** version and record the results in a
public issue, naming the app version, architecture, Home Assistant OS, Supervisor
and host versions, the image digest, timestamps and logs.

## Required checks

1. Add this repository and install FTW (beta) through the app store. Confirm
   that Supervisor pulls the pre-built image for the host architecture and
   that the digest matches the app's GitHub release record.
2. Start without `/data/config.yaml`. Confirm that the setup page opens and the
   app becomes healthy.
3. Complete setup. Confirm that `/api/status` returns valid JSON and that
   Settings → System shows the bundled FTW version.
4. Restart the app and the host. Confirm that config, state, history,
   `/data/drivers` and `/data/driver-repository` remain intact.
5. Confirm that no FTW updater process or Docker socket exists in the app and
   that the update buttons are absent from the FTW web interface.
6. Update from the previous beta to the next one through Supervisor. Confirm
   that Supervisor performs the update and that data survives.
7. Roll back through Supervisor to the previous version, then restore the
   matching Home Assistant backup. Confirm that FTW starts with that state.
8. Confirm in the FTW log that the Energyplan worker is active and that Core
   keeps planning on its Go fallback when the worker is unavailable.

## Record the result

Open a pull request that sets, in `compatibility.yaml`:

```yaml
qualification:
  home_assistant_os_supervisor:
    status: passed
    add_on_version: <the beta version the checks ran on>
    evidence: <public issue or report URL>
    checklist: pilot/README.md
```

From the next sync run, every FTW stable release promotes the matching beta
into the **FTW** app. Set `status: blocked` again to stop promotions if the
packaging regresses; published stable versions stay available.
