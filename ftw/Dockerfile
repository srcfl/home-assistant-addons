# syntax=docker/dockerfile:1.7

# The app is the pinned FTW Core image plus a Supervisor wrapper. Core already
# carries the compiled Energyplan worker, its Go planner fallback, tzdata,
# ca-certificates and the wget its own health check uses, so nothing is
# installed here and the build needs no network access.
#
# One image serves both apps in this repository: `ftw-beta` installs the tag of
# an FTW beta, `ftw` installs the tag FTW promoted to stable. Stable promotion
# re-tags the beta digest; it never rebuilds this file.
ARG FTW_CORE_FROM
FROM ${FTW_CORE_FROM}

ARG BUILD_ARCH
ARG BUILD_VERSION
ARG BUILD_SHA=""
ARG CORE_VERSION
ARG CORE_DIGEST

# The wrapper needs root only to prepare Supervisor's fresh /data mount. It
# hands the process to uid 100, gid 101, the identity Core uses everywhere.
# hadolint ignore=DL3002
USER root

COPY run.sh healthcheck.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/run.sh /usr/local/bin/healthcheck.sh \
    && mkdir -p /data/drivers /data/driver-repository \
    && chown 100:101 /data /data/drivers /data/driver-repository

# FTW_IMAGE_TAG selects the release identity Core reports. The beta build bakes
# the beta tag; config.yaml of the stable app overrides it with the stable tag,
# which the same Core digest also binds once FTW has promoted it.
ENV HOME=/data \
    FTW_SELFUPDATE_ENABLED=0 \
    FTW_BUNDLE=home_assistant_addon \
    FTW_BUNDLE_VERSION=${BUILD_VERSION} \
    FTW_IMAGE_TAG=${CORE_VERSION}

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
    com.sourceful.ftw.update-owner="home_assistant_supervisor"

WORKDIR /data
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=8 \
    CMD ["/usr/local/bin/healthcheck.sh"]

# config.yaml leaves Supervisor's `init` at its default, so Docker's init is
# PID 1 and Core, started with exec below, is its only child.
ENTRYPOINT ["/usr/local/bin/run.sh"]
