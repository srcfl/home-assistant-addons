# syntax=docker/dockerfile:1.7

# FTW 0.x for Home Assistant, built from the same checksummed release package
# the native installer and deploy/docker in srcfl/ftw use. Nothing is compiled.
# Supervisor builds this on the device (config.yaml has no `image:`), so the
# app never depends on a registry image.
FROM docker.io/library/debian:trixie-slim

ARG BUILD_ARCH
ARG BUILD_VERSION=0.0.0-dev
# Pins written by scripts/native_pin.py from ftw-native-release.json.
ARG FTW_VERSION=v0.157.3-beta.1
ARG FTW_SHA256_AMD64=691a6423686f4f5a447d200b64c29875d96f4f152918a9d89438f7b50c860426
ARG FTW_SHA256_ARM64=e76b25c9119558bef61cd6832042c8f8a8b6aeb8d085909f0b01cadfe9bed2a9

# ca-certificates/curl fetch the package; tzdata keeps plan windows right;
# wget is what healthcheck.sh uses; setpriv (util-linux) drops to uid 100.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tzdata wget util-linux \
    && rm -rf /var/lib/apt/lists/*

# The expected hash is pinned above and must also equal the release's
# own .sha256 file, so a swapped release asset cannot slip in.
RUN set -eu; \
    test -n "${FTW_VERSION}" || { echo "FTW_VERSION is required" >&2; exit 1; }; \
    case "${BUILD_ARCH:-$(dpkg --print-architecture)}" in \
      amd64) arch=amd64; want="${FTW_SHA256_AMD64}" ;; \
      aarch64|arm64) arch=arm64; want="${FTW_SHA256_ARM64}" ;; \
      *) echo "unsupported arch ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac; \
    test -n "${want}" || { echo "no pinned sha256 for ${arch}" >&2; exit 1; }; \
    pkg="ftw-linux-${arch}.tar.gz"; \
    url="https://github.com/srcfl/ftw/releases/download/${FTW_VERSION}"; \
    cd /tmp; \
    curl -fsSLO "${url}/${pkg}" -O "${url}/${pkg}.sha256"; \
    echo "${want}  ${pkg}" | sha256sum -c -; \
    sha256sum -c "${pkg}.sha256"; \
    mkdir -p /app; \
    tar -xzf "${pkg}" -C /app; \
    rm "${pkg}" "${pkg}.sha256"; \
    rm -f /app/ftw-launcher; \
    ln -s /app/ftw-cli /usr/local/bin/ftw; \
    chown -R 0:0 /app

COPY run.sh healthcheck.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/run.sh /usr/local/bin/healthcheck.sh

ENV HOME=/data \
    FTW_SELFUPDATE_ENABLED=0 \
    FTW_BUNDLE=home_assistant_addon \
    FTW_BUNDLE_VERSION=${BUILD_VERSION} \
    FTW_IMAGE_TAG=${FTW_VERSION}

LABEL io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.version="${BUILD_VERSION}" \
    org.opencontainers.image.title="Sourceful FTW 0.x for Home Assistant" \
    org.opencontainers.image.source="https://github.com/srcfl/home-assistant-addons" \
    org.opencontainers.image.licenses="Apache-2.0" \
    com.sourceful.ftw.core.version="${FTW_VERSION}" \
    com.sourceful.ftw.core.sha256.amd64="${FTW_SHA256_AMD64}" \
    com.sourceful.ftw.core.sha256.arm64="${FTW_SHA256_ARM64}" \
    com.sourceful.ftw.update-owner="home_assistant_supervisor"

WORKDIR /data
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=8 \
    CMD ["/usr/local/bin/healthcheck.sh"]
ENTRYPOINT ["/usr/local/bin/run.sh"]
