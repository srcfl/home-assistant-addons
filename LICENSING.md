# Licensing

This repository holds Home Assistant packaging: app manifests, Dockerfiles,
wrapper scripts, docs, tests and release tools. The packaging uses the
[Apache License 2.0](LICENSE).

The apps install FTW, which keeps its own licenses. Installing FTW through
Home Assistant does not change them.

| Part | License | Text in the FTW 0.x app |
|---|---|---|
| Packaging in this repository | Apache-2.0 | [LICENSE](LICENSE) and [NOTICE](NOTICE) here |
| FTW Core, its web UI and the drivers it bundles | AGPL-3.0-only, with the Energyplan combination permission | `/app/LICENSE`, `/app/NOTICE`, `/app/LICENSING.md` |
| Energyplan worker | Energyplan Home Use Binary License 1.0 | `/app/optimizer/native/bundle/LICENSE.txt` |
| Third-party code in FTW and the worker | Each its own | `/app/THIRD-PARTY-NOTICES.txt`, `/app/optimizer/native/bundle/THIRD-PARTY-NOTICES.txt` |
| Debian base image packages | Each its own | `/usr/share/doc/*/copyright` |

The Energyplan license allows private household use with FTW. Commercial use,
bundling, resale and services need a separate license from Sourceful. An
older driver snapshot keeps the license it was published under. FTW's
[LICENSING.md](https://github.com/srcfl/ftw/blob/master/LICENSING.md) explains
these terms; the files in the app are the ones that apply to that version.

The image label `org.opencontainers.image.licenses` lists the same three
licenses. `LicenseRef-Energyplan-Home-Use-1.0` there means the Energyplan
license above.

## Source

FTW's source is at <https://github.com/srcfl/ftw>. Use the tag the app pins,
not the default branch. The tag is `FTW_VERSION` in
[ftw-0x-beta/Dockerfile](ftw-0x-beta/Dockerfile), and the image shows it in
the `com.sourceful.ftw.core.version` label. The app installs FTW's own release
package unchanged.

## Retired apps

The retired 3.x images built from [ftw/Dockerfile](ftw/Dockerfile) carry the
licenses of the Core version each one pinned. Read them inside the image under
`/usr/share/doc/ftw/`. Core moved to AGPL-3.0-only on 12 September 2026, so
3.x releases from then on, such as 3.8.0-beta.1, include AGPL Core and the
Energyplan Home Use worker. Images published before this file changed show
only `Apache-2.0` in their label; the files inside the image apply.
