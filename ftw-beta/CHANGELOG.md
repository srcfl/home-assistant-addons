# Changelog

## 3.7.1-beta.1

- Update Core to v3.7.1-beta.1 (`sha256:db6db21db27b1c24b8cdfde8a765a84968e898e1be7da1248a584098104bb11d`).
- Record the stable driver baseline `f18ceef626c5`.

## 3.4.2-beta.4

- First version of the beta app. Pins Core v3.4.2-beta.4
  (`sha256:06ab3751d55527dc557c239307124ab9c131401bba83057b3cb4b52c0643864c`).
- The app is the Core image alone plus the Supervisor wrapper. Core bundles
  the Energyplan worker and its Go planner fallback; the separate Python
  optimizer image and its Unix socket are gone.
- The app version now mirrors the Core version.
