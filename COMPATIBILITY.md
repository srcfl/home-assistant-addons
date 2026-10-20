# Compatibility

## Native 0.x beta

`ftw-0x-beta/config.yaml` and `ftw-0x-beta/Dockerfile` pin the app and Core
version and the package SHA-256 for amd64 and arm64. `native_pin.py check`
compares them with the published native receipt and checksum files.
The package includes Core, web assets, bundled recovery drivers and Energyplan.
Managed drivers still use Core's signed driver channel.

CI builds and runs the real package on both amd64 and aarch64. It checks setup,
Energyplan's handshake, restart, persistence, cold restore with root-owned files,
and process death. It also checks that ownership repair refuses hard links and
nested mounts and that the runtime directories cannot be symbolic links.

The [0.x app PR](https://github.com/srcfl/home-assistant-addons/pull/21) records
the Home Assistant OS/Supervisor VM results and remaining physical-site checks.
No physical Home Assistant Green or attached energy equipment has passed
qualification yet. Follow [the pilot checks](pilot/README.md).

## Retired apps

The records below describe the retired app, not current install recommendations.
2.x and 3.x receive no more updates. The app does not follow new 0.x; see
[the install choices](README.md).

`compatibility.yaml` (schema 2) is the source of truth for what each app
installs. The app version mirrors the FTW Core version it runs.

| Block | Meaning |
|---|---|
| `image` | The one image both apps install, tagged by app version. |
| `beta` | The `ftw-beta` app: its version and the exact Core release, commit and multi-arch digest it was built from. |
| `stable` | The `ftw` app: its version, the beta it was promoted from, that beta's image digest and source commit, and the Core release FTW promoted. All `null` until the first promotion. |
| `drivers` | The managed driver channel Core fetches at run time, and the signed stable manifest recorded at the last pin. Drivers update independently of the app; the bundled set is offline recovery only. |
| `qualification` | The one-time Home Assistant OS and Supervisor pilot that gates stable promotion. See [pilot/README.md](pilot/README.md). |

The old sync workflow wrote `beta`, `stable` and `drivers.tested_baseline`.
People recorded `qualification`. Do not interpret that workflow as a current
release path. There is no FTW updater field or image: Supervisor owns
updates and rollback.

Each published version also carries an immutable `release-manifest.json` on
its GitHub release with the same Core coordinates, the multi-arch manifest
digest and the source commit.
