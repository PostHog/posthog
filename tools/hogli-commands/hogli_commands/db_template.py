"""Fill an empty pytest database by cloning a migrated template instead of replaying every migration.

The template is the schema dump that master CI publishes (see db_schema), restored once per
Postgres server. Each test database is then a `CREATE DATABASE ... TEMPLATE` copy, and Django's
keepdb migrate applies only the migrations newer than the template.
"""

from __future__ import annotations

import os
import gzip
import time
import shutil
import tempfile
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from hogli_commands.db_schema import (
    REPO_ROOT,
    MigrationReference,
    check_dump_is_not_newer_than_checkout,
    download_schema_artifact,
    find_newest_compatible_artifact,
    github_session,
    migrations_missing_from_checkout,
    product_routed_app_labels,
    run_psql_with_gzip_input,
)
from hogli_commands.github_auth import github_token

TEMPLATE_PREFIX = "test_posthog_template_"
BUILDING_SUFFIX = "_building"
TEMPLATE_SHA_LENGTH = 12
TEMPLATES_KEPT = 3
TEMPLATE_MAX_LAG_SECONDS = 24 * 60 * 60
TEMPLATE_BUILD_LOCK = 0x7465_6D70_6C61_7465
MODE_ENV = "POSTHOG_TEST_DB_TEMPLATE"
REFRESH_RETRY_SECONDS = 15 * 60
LIBPQ_TLS_OPTIONS = ("sslmode", "sslrootcert", "sslcert", "sslkey", "sslpassword", "sslcrl", "sslnegotiation")


class TemplateUnavailable(Exception):
    pass


@dataclass(frozen=True, kw_only=True, slots=True)
class PostgresServer:
    host: str
    port: str
    user: str
    password: str
    tls: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_django(cls, database: Mapping[str, Any]) -> PostgresServer:
        options = database.get("OPTIONS") or {}
        return cls(
            host=database.get("HOST") or "localhost",
            port=str(database.get("PORT") or "5432"),
            user=database.get("USER") or "posthog",
            password=database.get("PASSWORD") or "",
            tls={key: str(options[key]) for key in LIBPQ_TLS_OPTIONS if options.get(key)},
        )

    def conninfo(self, dbname: str) -> str:
        """Everything but the password, which psql takes from its environment rather than its argv."""
        return make_conninfo(host=self.host, port=self.port, user=self.user, dbname=dbname, **self.tls)

    def connect(self, dbname: str) -> psycopg.Connection:
        return psycopg.connect(self.conninfo(dbname), password=self.password, autocommit=True, connect_timeout=5)

    def database_exists(self, dbname: str) -> bool:
        with self.connect("postgres") as admin:
            return admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone() is not None

    def create_database(self, dbname: str, *, template: str = "template0") -> None:
        statement = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
        self._admin(statement.format(sql.Identifier(dbname), sql.Identifier(template)))

    def rename_database(self, dbname: str, new_name: str) -> None:
        self._admin(sql.SQL("ALTER DATABASE {} RENAME TO {}").format(sql.Identifier(dbname), sql.Identifier(new_name)))

    def drop_database(self, dbname: str) -> None:
        self._admin(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(dbname)))

    def newest_databases_named(self, prefix: str) -> list[str]:
        with self.connect("postgres") as admin:
            rows = admin.execute(
                "SELECT datname FROM pg_database WHERE starts_with(datname, %s) ORDER BY oid DESC", (prefix,)
            ).fetchall()
        return [name for (name,) in rows]

    def recorded_migrations(self, dbname: str) -> set[MigrationReference]:
        with self.connect(dbname) as connection:
            if connection.execute("SELECT to_regclass('django_migrations')").fetchone() == (None,):
                return set()
            rows = connection.execute("SELECT app, name FROM django_migrations").fetchall()
        return {MigrationReference(app=app, name=name) for app, name in rows}

    def forget_migrations(self, dbname: str, apps: list[str]) -> None:
        with self.connect(dbname) as connection:
            connection.execute("DELETE FROM django_migrations WHERE app = ANY(%s)", (apps,))

    def load_gzip_dump(self, dbname: str, dump: Path) -> None:
        psql = shutil.which("psql")
        if psql is None:
            run_psql_with_gzip_input(dump, dbname)
            return
        with gzip.open(dump, "rb") as source:
            subprocess.run(
                [psql, "-q", "-v", "ON_ERROR_STOP=1", "--single-transaction", self.conninfo(dbname)],
                input=source.read(),
                env={**os.environ, "PGPASSWORD": self.password},
                stdout=subprocess.DEVNULL,
                check=True,
            )

    @contextmanager
    def build_lock(self) -> Iterator[None]:
        with self.connect("postgres") as admin:
            admin.execute("SELECT pg_advisory_lock(%s)", (TEMPLATE_BUILD_LOCK,))
            try:
                yield
            finally:
                admin.execute("SELECT pg_advisory_unlock(%s)", (TEMPLATE_BUILD_LOCK,))

    def _admin(self, statement: sql.Composed) -> None:
        with self.connect("postgres") as admin:
            admin.execute(statement)


class Checkout:
    def __init__(self, root: Path = REPO_ROOT, *, master_ref: str = "origin/master") -> None:
        self.root = root
        self.master_ref = master_ref
        self._contains: dict[str, bool] = {}

    def contains(self, sha: str) -> bool:
        if sha not in self._contains:
            self._contains[sha] = self._git("merge-base", "--is-ancestor", sha, "HEAD") is not None
        return self._contains[sha]

    def lags_master_base(self, sha: str, *, by_seconds: int) -> bool:
        """Whether sha is older than the master commit this checkout last merged, by more than by_seconds."""
        base = self._git("merge-base", "HEAD", self.master_ref) or "HEAD"
        base_time, sha_time = self._commit_time(base), self._commit_time(sha)
        return base_time is None or sha_time is None or base_time - sha_time > by_seconds

    def _commit_time(self, revision: str) -> int | None:
        output = self._git("show", "-s", "--format=%ct", revision)
        return int(output) if output else None

    def _git(self, *args: str) -> str | None:
        result = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, timeout=30)
        return result.stdout.strip() if result.returncode == 0 else None


class TemplateStore:
    """Migrated template databases on one Postgres server, one per master commit that CI dumped."""

    def __init__(
        self,
        server: PostgresServer,
        checkout: Checkout,
        *,
        allow_download: bool = True,
        prefix: str = TEMPLATE_PREFIX,
        failure_marker: Path | None = None,
    ) -> None:
        self.server = server
        self.checkout = checkout
        self.allow_download = allow_download
        self.prefix = prefix
        self.failure_marker = failure_marker or Path(tempfile.gettempdir()) / (
            f"{prefix}{server.host}_{server.port}.download-failed"
        )

    def name_for(self, sha: str) -> str:
        return self.prefix + sha[:TEMPLATE_SHA_LENGTH]

    def usable_template(self) -> str | None:
        with self.server.build_lock():
            local = self._newest_local_template()
            if not self.allow_download or (local is not None and not self._lags_master(local)):
                return local
            if self._download_failed_recently():
                if local is None:
                    raise TemplateUnavailable(
                        f"the last download failed less than {REFRESH_RETRY_SECONDS // 60} minutes ago"
                    )
                return local
            try:
                built = self._build_from_newest_artifact()
            except Exception:
                self.failure_marker.touch()
                if local is None:
                    raise
                return local
            self.failure_marker.unlink(missing_ok=True)
            self._prune(keep=built)
            return built

    def build(self, name: str, dump: Path) -> None:
        check_dump_is_not_newer_than_checkout(dump)
        building = name + BUILDING_SUFFIX
        self.server.drop_database(building)
        self.server.create_database(building)
        try:
            self.server.load_gzip_dump(building, dump)
            if apps := product_routed_app_labels():
                self.server.forget_migrations(building, apps)
            self.server.rename_database(building, name)
        except Exception:
            self.server.drop_database(building)
            raise

    def _newest_local_template(self) -> str | None:
        for name in self.server.newest_databases_named(self.prefix):
            if not name.endswith(BUILDING_SUFFIX) and self.checkout.contains(name.removeprefix(self.prefix)):
                return name
        return None

    def _download_failed_recently(self) -> bool:
        try:
            return time.time() - self.failure_marker.stat().st_mtime < REFRESH_RETRY_SECONDS
        except FileNotFoundError:
            return False

    def _lags_master(self, name: str) -> bool:
        sha = name.removeprefix(self.prefix)
        return self.checkout.lags_master_base(sha, by_seconds=TEMPLATE_MAX_LAG_SECONDS)

    def _build_from_newest_artifact(self) -> str:
        token = github_token()
        session = github_session()
        artifact = find_newest_compatible_artifact(
            token=token, session=session, accept=lambda candidate: self.checkout.contains(candidate.head_sha)
        )
        if artifact is None:
            raise TemplateUnavailable("no recent master schema dump is an ancestor of this checkout")
        name = self.name_for(artifact.head_sha)
        if not self.server.database_exists(name):
            with tempfile.TemporaryDirectory(prefix="test-db-template-") as scratch:
                dump = Path(scratch) / "schema.sql.gz"
                download_schema_artifact(artifact, token=token, destination=dump, session=session)
                self.build(name, dump)
        return name

    def _prune(self, *, keep: str) -> None:
        older = [name for name in self.server.newest_databases_named(self.prefix) if name != keep][TEMPLATES_KEPT - 1 :]
        for name in older:
            try:
                self.server.drop_database(name)
            except psycopg.Error:
                continue


class PrimeOutcome(StrEnum):
    KEPT = "kept"
    CLONED = "cloned"
    SKIPPED = "skipped"


@dataclass(frozen=True, kw_only=True, slots=True)
class PrimeResult:
    outcome: PrimeOutcome
    detail: str


def prime_test_database(server: PostgresServer, target_db: str, store: TemplateStore) -> PrimeResult:
    """Leave target_db ready for Django's keepdb migrate, cloning a template when it holds nothing usable."""
    exists = server.database_exists(target_db)
    if exists:
        recorded = server.recorded_migrations(target_db)
        missing = migrations_missing_from_checkout(recorded)
        if recorded and not missing:
            return PrimeResult(outcome=PrimeOutcome.KEPT, detail=f"{target_db} fits this checkout")
    template = store.usable_template()
    if template is None:
        return PrimeResult(outcome=PrimeOutcome.SKIPPED, detail="no template database is available")
    if exists:
        try:
            server.drop_database(target_db)
        except psycopg.errors.ObjectInUse:
            reason = f"records {len(missing)} migrations this checkout lacks" if missing else "has no migrations"
            return PrimeResult(outcome=PrimeOutcome.SKIPPED, detail=f"{target_db} {reason} and another session uses it")
    server.create_database(target_db, template=template)
    return PrimeResult(outcome=PrimeOutcome.CLONED, detail=f"cloned {target_db} from {template}")


def prime_django_test_database(default_db: Mapping[str, Any]) -> PrimeResult | None:
    """Prime the test database of Django's default alias. Off in CI, which restores its own."""
    if os.environ.get(MODE_ENV, "off" if os.environ.get("CI") else "auto") == "off":
        return None
    server = PostgresServer.from_django(default_db)
    target_db = default_db.get("TEST", {}).get("NAME") or f"test_{default_db['NAME']}"
    try:
        return prime_test_database(server, target_db, TemplateStore(server, Checkout()))
    except Exception as exc:
        return PrimeResult(outcome=PrimeOutcome.SKIPPED, detail=f"{type(exc).__name__}: {exc}")
