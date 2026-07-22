# Attribution and source trail

This repository carries forward work from two earlier efforts.

## Community add-on

Erik Arenhill created
[`erikarenhill/ha-addon-forty-two-watts`](https://github.com/erikarenhill/ha-addon-forty-two-watts)
and maintained it from `0.1.0` through `1.4.0`. It proved the basic Home
Assistant package: a root `repository.yaml`, `amd64` and `aarch64`, host
networking, port 8080, `/data`, and a direct Web UI link.

The official package keeps those choices where they still match current Home
Assistant and FTW rules. It does not copy the old version-bump workflow because
the app, Core, and Optimizer now have separate versions and test gates.

## FTW PR #620

HuggeK authored
[`srcfl/ftw#620`](https://github.com/srcfl/ftw/pull/620), including the first
combined Core and Optimizer Dockerfile, process wrapper, Home Assistant docs,
and storage notes. The official package adapts that work as follows:

- moves `repository.yaml` to the root of its own repo;
- uses a pre-built generic multi-arch image;
- removes obsolete `build.yaml` use;
- gives the app its own version;
- pins Core and Optimizer by separate digest and protocol contract;
- uses Unix-only optimizer transport so faults reach Core's Go fallback;
- leaves updates and rollback to Home Assistant Supervisor;
- treats `srcfl/device-drivers` as the normal driver source and bundled
  drivers as offline recovery;
- keeps `/data/drivers` apart from managed drivers.

The FTW brand PNG comes unchanged from `srcfl/ftw/web/logo.png`.
