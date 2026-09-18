# Changelog

## 3.4.2-beta.4

- First version of the beta app. Pins Core v3.4.2-beta.4
  (`sha256:06ab3751d55527dc557c239307124ab9c131401bba83057b3cb4b52c0643864c`).
- The app is the Core image alone plus the Supervisor wrapper. Core bundles
  the Energyplan worker and its Go planner fallback; the separate Python
  optimizer image and its Unix socket are gone.
- The app version now mirrors the Core version.
