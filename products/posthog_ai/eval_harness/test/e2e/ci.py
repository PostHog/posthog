from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path

from .metrics import ResourceMonitor


def main() -> int:
    root = Path(__file__).resolve().parents[5]
    output = root / "products/posthog_ai/frontend/e2e/artifacts/ci"
    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "CI": "true",
            "DEBUG": "1",
            "E2E_TESTING": "1",
            "SELF_CAPTURE": "0",
            "OPT_OUT_CAPTURE": "1",
            "CLOUD_DEPLOYMENT": "E2E",
            "SECRET_KEY": "synthetic-ai-e2e-secret",
            "DATABASE_URL": "postgres://posthog:posthog@localhost:5432/posthog_ai_e2e",
            "PERSONS_DB_WRITER_URL": "postgres://posthog:posthog@localhost:5432/posthog_ai_e2e_persons",
            "PERSONS_DB_READER_URL": "postgres://posthog:posthog@localhost:5432/posthog_ai_e2e_persons",
            "POSTHOG_PERSONS_DB_NAME": "posthog_ai_e2e_persons",
            "REDIS_URL": "redis://localhost:6379",
            "CLICKHOUSE_HOST": "localhost",
            "CLICKHOUSE_DATABASE": "posthog_test",
            "CLICKHOUSE_SECURE": "false",
            "CLICKHOUSE_VERIFY": "false",
            "KAFKA_HOSTS": "kafka:9092",
            "TEMPORAL_HOST": "localhost",
            "TEMPORAL_PORT": "7233",
            "TEMPORAL_NAMESPACE": "default",
            "PGHOST": "localhost",
            "PGPORT": "5432",
            "PGUSER": "posthog",
            "PGPASSWORD": "posthog",
            "OBJECT_STORAGE_ENABLED": "1",
            "OBJECT_STORAGE_ENDPOINT": "http://localhost:19000",
            "OBJECT_STORAGE_ACCESS_KEY_ID": "object_storage_root_user",
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": "object_storage_root_password",
            "COMPOSE_PROJECT_NAME": "posthog-ai-e2e",
            "COMPOSE_FILE": "docker-compose.dev.yml:docker-compose.profiles.yml",
            "COMPOSE_PROFILES": "temporal,ingestion",
            "PERSONHOG_ADDR": "localhost:50052",
            "INTERNAL_API_SECRET": "posthog123",
            "STATIC_PRECOMPRESS": "0",
            "SKIP_SERVICE_VERSION_REQUIREMENTS": "1",
        }
    )

    def run(*command: str) -> None:
        with monitor.stage(" ".join(command[:2])):
            subprocess.run(command, cwd=root, check=True)

    services = ("db", "redis7", "kafka", "clickhouse", "objectstorage", "temporal")
    monitor = ResourceMonitor()
    try:
        shutil.copyfile(
            root / "posthog/user_scripts/latest_user_defined_function.xml",
            root / "docker/clickhouse/user_defined_function.xml",
        )
        run("bin/ci-wait-for-docker", "launch", *services)
        run("bin/ci-wait-for-docker", "wait", *services)
        run("createdb", "posthog_ai_e2e")
        if (root / "schema.sql.gz").exists():
            backups = root / ".postgres-backups"
            backups.mkdir(exist_ok=True)
            shutil.copyfile(root / "schema.sql.gz", backups / "schema-latest.sql.gz")
            with monitor.stage("schema_restore"):
                restored = subprocess.run(
                    ["hogli", "db:restore-schema-fresh"],
                    cwd=root,
                    env={**os.environ, "TARGET_DB": "posthog_ai_e2e"},
                )
            if restored.returncode:
                sys.stderr.write("Schema restore failed; applying migrations to the fresh database.\n")
                run("dropdb", "--if-exists", "posthog_ai_e2e")
                run("createdb", "posthog_ai_e2e")
        run("python", "manage.py", "migrate", "--noinput")
        persons_url = os.environ["PERSONS_DB_WRITER_URL"]
        run("sqlx", "database", "create", "-D", persons_url)
        run("sqlx", "migrate", "run", "-D", persons_url, "--source", "rust/persons_migrations")
        run("python", "manage.py", "migrate_clickhouse")
        run("bin/ci-wait-for-docker", "launch", "personhog-replica", "personhog-router")
        run("bin/ci-wait-for-docker", "wait", "personhog-replica", "personhog-router")
        run("bin/turbo", "--filter=@posthog/frontend", "prepare")
        run("pnpm", "--filter=@posthog/frontend", "build:products")
        run("pnpm", "--filter=@posthog/frontend", "build")
        run("python", "manage.py", "collectstatic", "--noinput")
        run("pnpm", "--filter=@posthog/playwright", "exec", "playwright", "install", "chromium", "--with-deps")
        with monitor.stage("suite"):
            return subprocess.run(
                ["hogli", "test:e2e:ai", "--attach", *sys.argv[1:]],
                cwd=root,
                env={**os.environ, "AI_E2E_SCHEMA_TEMPLATE": "posthog_ai_e2e"},
            ).returncode
    finally:
        (output / "metrics.json").write_text(json.dumps(monitor.finish(), indent=2))
        with (output / "docker.log").open("w") as log:
            subprocess.run(["docker", "compose", "logs", "--no-color"], cwd=root, stdout=log, stderr=subprocess.STDOUT)
        subprocess.run(["docker", "compose", "down", "--volumes"], cwd=root, check=True)


if __name__ == "__main__":
    sys.exit(main())
