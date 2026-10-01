from __future__ import annotations

from django.conf import settings


class EnvironmentMigrationsPending(RuntimeError):
    pass


def assert_local_databases() -> dict[str, str]:
    if not settings.DEBUG or settings.CLOUD_DEPLOYMENT:
        raise RuntimeError("Environment imports require DEBUG and no CLOUD_DEPLOYMENT.")
    allowed = {"", "localhost", "127.0.0.1", "::1", "db", "postgres", "clickhouse"}
    for database in settings.DATABASES.values():
        host = str(database.get("HOST", ""))
        if host not in allowed and not host.startswith("/"):
            raise RuntimeError("Environment imports require local database hosts.")
    for name in ("CLICKHOUSE_HOST", "CLICKHOUSE_STABLE_HOST", "QUERYSERVICE_HOST"):
        if str(getattr(settings, name, settings.CLICKHOUSE_HOST)) not in allowed - {""}:
            raise RuntimeError("Environment imports require local ClickHouse hosts.")
    database = settings.DATABASES["default"]
    return {
        "postgres_host": str(database.get("HOST", "")),
        "postgres_port": str(database.get("PORT", "")),
        "postgres_database": str(database["NAME"]),
        "clickhouse_host": str(settings.CLICKHOUSE_HOST),
        "clickhouse_database": str(settings.CLICKHOUSE_DATABASE),
    }
