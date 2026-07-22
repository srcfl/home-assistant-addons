# Home Assistant OS and Supervisor pilot

Use a test host that matches a supported architecture. Record the Home
Assistant OS, Supervisor, and host versions, all image digests, timestamps, and
logs in a public issue or test report. Fill the candidate record in
[`0.1.0-beta.1.yaml`](0.1.0-beta.1.yaml) and link each result to public
evidence.

## Required checks

1. Add this repository and install the beta through the app store. Confirm that
   Supervisor pulls the pre-built image for the host architecture.
2. Start without `/data/config.yaml`. Confirm that the setup page opens and the
   container becomes healthy.
3. Complete setup. Confirm that `/api/status` returns valid JSON only after
   Core opens and migrates its state.
4. Restart the app and the host. Confirm that config, SQLite state, history,
   `/data/drivers`, and `/data/driver-repository` remain intact.
5. Stop the Optimizer process. Confirm that Core stays ready, uses the Go
   planner, and reconnects after the worker restarts.
6. Test a wrong socket, bad handshake, and solve error. Each must use the Go
   planner without a Core crash or a hidden local Python worker.
7. Update from the last supported add-on beta. Confirm that Supervisor owns the
   update and that no FTW updater process or Docker socket exists in the app.
8. Roll back to the prior version and restore its cold backup. Confirm that FTW
   starts with the prior state.
9. Update to the candidate beta again. Confirm that the pulled manifest digest
   matches the signed release record.
10. Run an active solver request and confirm Optimizer protocol 1, plan schema
    1, and the required feature set. Test `recourse` and `multistage` when the
    site uses those policies.

Do not mark the add-on stable or production-ready when any check lacks real
Home Assistant OS and Supervisor evidence.
