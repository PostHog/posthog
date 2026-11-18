# Postgres for the integration tests, with the extensions infra installs on the deployed database.
FROM postgres:17-bookworm
# The PGDG repository keeps only current package versions, so a pinned version stops building.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-partman postgresql-17-cron \
    && rm -rf /var/lib/apt/lists/*
