# syntax=docker/dockerfile:1.7

ARG FTW_CORE_FROM
ARG FTW_OPTIMIZER_FROM

FROM ${FTW_CORE_FROM} AS core
FROM ${FTW_OPTIMIZER_FROM}

ARG BUILD_ARCH
ARG BUILD_VERSION
ARG BUILD_SHA=""
ARG CORE_VERSION
ARG CORE_DIGEST
ARG OPTIMIZER_VERSION
ARG OPTIMIZER_DIGEST

# The wrapper needs root only to prepare Supervisor's fresh /data mount. It
# starts Core and Optimizer as uid 100, gid 101.
# hadolint ignore=DL3002
USER root

# Release inputs and outputs use image digests. Debian does not keep old package
# revisions in its normal index, so pinning this small runtime set would break
# later rebuilds without adding a stronger release guarantee.
#
# The suite comes from FTW_OPTIMIZER_FROM, which moved to
# python:3.12-slim-trixie in srcfl/ftw#731. Verified on that base: all three
# packages resolve and tini still lands at /usr/bin/tini, which the ENTRYPOINT
# below depends on.
#
# libnss-mdns is deliberately NOT installed here, unlike in the Core image. It
# only forwards to avahi-daemon over /run/avahi-daemon/socket, and Supervisor
# gives an app no way to bind an arbitrary host path, so it would resolve
# nothing. There is no avahi on HA OS to reach in any case — the multicast
# plugin is mdns-repeater, a packet relay with no query API.
#
# It is not needed. Supervisor points this container at its own CoreDNS, which
# carries an mdns plugin backed by systemd-resolved, and that answers ".local"
# over ordinary unicast DNS — confirmed on a pilot install, where a lookup
# failure reads "on 172.30.32.3:53". host_network in config.yaml is what puts
# the app on the device's network segment.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates tini tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=core /app/ftw /app/ftw
COPY --from=core /app/web /app/web
COPY --from=core /app/drivers /app/drivers
COPY run.sh healthcheck.py /usr/local/bin/

RUN chmod 0755 /usr/local/bin/run.sh /usr/local/bin/healthcheck.py \
    && mkdir -p /data/drivers /data/driver-repository /run/ftw /run/ftw-optimizer \
    && chown 100:101 /data /data/drivers /data/driver-repository \
       /run/ftw /run/ftw-optimizer

ENV HOME=/data \
    FTW_SELFUPDATE_ENABLED=0 \
    FTW_OPTIMIZER_TRANSPORT=unix \
    FTW_OPTIMIZER_SOCKET=/run/ftw-optimizer/optimizer.sock

LABEL io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.version="${BUILD_VERSION}" \
    org.opencontainers.image.title="Sourceful FTW for Home Assistant" \
    org.opencontainers.image.description="Official Sourceful FTW Home Assistant app" \
    org.opencontainers.image.url="https://github.com/srcfl/home-assistant-addons" \
    org.opencontainers.image.source="https://github.com/srcfl/home-assistant-addons" \
    org.opencontainers.image.revision="${BUILD_SHA}" \
    org.opencontainers.image.version="${BUILD_VERSION}" \
    org.opencontainers.image.licenses="Apache-2.0" \
    com.sourceful.ftw.core.version="${CORE_VERSION}" \
    com.sourceful.ftw.core.digest="${CORE_DIGEST}" \
    com.sourceful.ftw.optimizer.version="${OPTIMIZER_VERSION}" \
    com.sourceful.ftw.optimizer.digest="${OPTIMIZER_DIGEST}" \
    com.sourceful.ftw.update-owner="home_assistant_supervisor"

WORKDIR /data
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=8 \
    CMD ["/usr/local/bin/healthcheck.py"]

ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/run.sh"]
