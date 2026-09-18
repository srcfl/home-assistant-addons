# Stands in for ghcr.io/srcfl/ftw in CI. The real image is debian:trixie-slim
# with wget, tzdata and ca-certificates, running as uid 100, gid 101 from
# /app/data. The app layers on top of it, so the fixture mirrors that contract
# on the same suite. The fake Core is a Python script only because this base
# ships Python; the app layer itself must never rely on it.
FROM python:3.12-slim-trixie

RUN apt-get update \
    && apt-get install --no-install-recommends -y wget \
    && rm -rf /var/lib/apt/lists/*

COPY app /app
RUN chmod 0755 /app/ftw \
    && mkdir -p /app/data \
    && chown -R 100:101 /app

ENV HOME=/app/data
USER 100:101
WORKDIR /app/data
EXPOSE 8080

ENTRYPOINT ["/app/ftw"]
CMD ["-config", "/app/data/config.yaml", "-web", "/app/web", "-drivers", "/app/drivers", "-user-drivers", "/app/data/drivers"]
