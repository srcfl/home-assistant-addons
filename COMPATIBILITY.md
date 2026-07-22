# Compatibility

The app has its own version. It does not copy the Core or Optimizer version.

| App | Core | Optimizer | Optimizer contract | Drivers | Update owner | State |
|---|---|---|---|---|---|---|
| `0.0.0-dev` | blocked | blocked | name `ftw-optimizer`; protocol `1`; plan schema `1`; `champion`, plus requested `recourse` or `multistage` | `srcfl/device-drivers` stable; bundled recovery | Home Assistant Supervisor | Bootstrap only |

The intended upstream candidates are Core `v1.10.0-beta.1` and Optimizer
`v1.3.2-beta.1`. They are not release pins. `compatibility.yaml` keeps
placeholders until both owners supply real digests and all upstream tests pass.

Stable requires the exact beta manifest digest and a real Home Assistant OS and
Supervisor test for build, boot, Core readiness, `/data` retention, update, and
Optimizer-to-Go-DP fallback.
