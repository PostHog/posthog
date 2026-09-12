from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


@contextmanager
def isolated_database(root: Path) -> Iterator[None]:
    from django.conf import settings
    from django.db import connections

    configuration = settings.DATABASES["default"]
    original_name = configuration["NAME"]
    name = f"test_ai_e2e_{uuid4().hex}"
    admin: dict[str, str] = {
        "dbname": "postgres",
        "user": str(configuration["USER"]),
        "password": str(configuration["PASSWORD"]),
        "host": str(configuration["HOST"] or "localhost"),
        "port": str(configuration["PORT"] or 5432),
    }
    url = (
        f"postgres://{quote(str(admin['user']), safe='')}:{quote(str(admin['password']), safe='')}"
        f"@{admin['host']}:{admin['port']}/{name}"
    )
    aliases = [alias for alias, config in settings.DATABASES.items() if config.get("NAME") == original_name]
    template = os.environ.get("AI_E2E_SCHEMA_TEMPLATE")
    if template:
        if template != "posthog_ai_e2e" or os.environ.get("CI") != "true":
            raise ValueError("Only the CI provisioner's empty database can serve as a schema template")
        with psycopg.connect(make_conninfo(**{**admin, "dbname": template})) as connection:
            if connection.execute("SELECT 1 FROM posthog_task LIMIT 1").fetchone():
                raise ValueError("The AI E2E schema template contains tasks")
    with psycopg.connect(make_conninfo(**admin), autocommit=True) as connection:
        query = (
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(name), sql.Identifier(template))
            if template
            else sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
        )
        connection.execute(query)
    try:
        connections.close_all()
        for alias in aliases:
            settings.DATABASES[alias]["NAME"] = name
            connections[alias].settings_dict["NAME"] = name
        with patch.dict(os.environ, {"DATABASE_URL": url, "PGDATABASE": name}):
            schema = root / "schema.sql.gz"
            if schema.exists() and not template:
                backups = root / ".postgres-backups"
                backups.mkdir(exist_ok=True)
                shutil.copyfile(schema, backups / "schema-latest.sql.gz")
                restored = subprocess.run(
                    ["hogli", "db:restore-schema-fresh"],
                    cwd=root,
                    env={
                        **os.environ,
                        "TARGET_DB": name,
                        "PGHOST": str(admin["host"]),
                        "PGPORT": str(admin["port"]),
                        "PGUSER": str(admin["user"]),
                        "PGPASSWORD": str(admin["password"]),
                    },
                )
                if restored.returncode:
                    with psycopg.connect(make_conninfo(**admin), autocommit=True) as connection:
                        connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
                        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            if not template:
                subprocess.run(["python", "manage.py", "migrate", "--noinput"], cwd=root, check=True)
            yield
    finally:
        connections.close_all()
        for alias in aliases:
            settings.DATABASES[alias]["NAME"] = original_name
            connections[alias].settings_dict["NAME"] = original_name
        with psycopg.connect(make_conninfo(**admin), autocommit=True) as connection:
            owned_databases = connection.execute(
                "SELECT datname FROM pg_database WHERE datname = %s OR starts_with(datname, %s)",
                (name, f"{name}_"),
            ).fetchall()
            for (owned_name,) in owned_databases:
                connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(owned_name)))
