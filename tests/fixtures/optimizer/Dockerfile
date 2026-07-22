FROM python:3.12-slim-bookworm

ENV FTW_OPTIMIZER_VERSION=fixture \
    FTW_OPTIMIZER_SOCKET=/run/ftw-optimizer/optimizer.sock

COPY ftw-optimizer ftw-optimizer-healthcheck /opt/venv/bin/
RUN chmod 0755 /opt/venv/bin/ftw-optimizer /opt/venv/bin/ftw-optimizer-healthcheck \
    && mkdir -p /run/ftw-optimizer \
    && chown -R 100:101 /run/ftw-optimizer /opt/venv

USER 100:101
ENTRYPOINT ["/opt/venv/bin/ftw-optimizer"]
