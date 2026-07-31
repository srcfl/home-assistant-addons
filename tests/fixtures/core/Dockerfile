# Tracks the base of the real Core image, which moved to Debian 13 "trixie" in
# srcfl/ftw#731. A fixture on a different suite would let a base-specific
# regression through the smoke test.
FROM python:3.12-slim-trixie

COPY app /app
RUN chmod 0755 /app/ftw

ENTRYPOINT ["/app/ftw"]
