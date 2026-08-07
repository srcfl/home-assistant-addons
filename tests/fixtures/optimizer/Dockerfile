# Tracks the base of the real Optimizer image, which now uses
# python:3.14-slim-trixie after srcfl/ftw#788. The add-on's own runtime layer is
# built on top of this image, so the fixture has to match the suite the real
# `apt-get install` will run against.
FROM python:3.14-slim-trixie

ENV FTW_OPTIMIZER_VERSION=fixture \
    FTW_OPTIMIZER_SOCKET=/run/ftw-optimizer/optimizer.sock

COPY ftw-optimizer ftw-optimizer-healthcheck /opt/venv/bin/
RUN chmod 0755 /opt/venv/bin/ftw-optimizer /opt/venv/bin/ftw-optimizer-healthcheck \
    && mkdir -p /run/ftw-optimizer \
    && chown -R 100:101 /run/ftw-optimizer /opt/venv

USER 100:101
ENTRYPOINT ["/opt/venv/bin/ftw-optimizer"]
