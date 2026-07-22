# Compatibility

The app has its own version. It does not copy the Core or Optimizer version.

| App | Core | Optimizer | Optimizer contract | Drivers | Update owner | State |
|---|---|---|---|---|---|---|
| `0.1.0-beta.1` | `v1.10.0-beta.1` at `sha256:03f98a…11dd5` | `v1.3.2-beta.1` at `sha256:3e595e…e79dc` | name `ftw-optimizer`; protocol `1`; plan schema `1`; `champion`, plus requested `recourse` or `multistage` | stable baseline commit `2939543a…4de8`, manifest SHA-256 `a1a4b0…5fa19`; independent updates; bundled recovery | Home Assistant Supervisor | Release inputs set; Home Assistant pilot blocked |

`compatibility.yaml` holds the full source commits and multi-architecture image
digests. It has no FTW updater field or image. The stable driver channel can
move on its own; the row records the exact driver baseline tested with this
candidate.

No add-on image has been published for this candidate. Stable requires the
exact beta manifest digest and a real Home Assistant OS and Supervisor test for
install, boot, Core readiness, `/data` retention, update, rollback, and
Optimizer-to-Go-planner fallback and recovery.
