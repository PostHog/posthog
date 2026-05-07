"""Postgres schema restore helpers for hogli."""

from __future__ import annotations

import os
import re
import gzip
import shutil
import zipfile
import tempfile
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import click
import requests

ArtifactMode = Literal["off", "auto", "on"]

GITHUB_REPOSITORY = "PostHog/posthog"
SCHEMA_ARTIFACT_NAME = "migrated-schema"
SCHEMA_DUMP_NAME = "schema.sql.gz"
LOCAL_SCHEMA_PATH = Path(".postgres-backups/schema-latest.sql.gz")
MIN_SCHEMA_ARTIFACT_BYTES = 10_000
DOCKER_COMPOSE = ["docker", "compose", "-f", "docker-compose.dev.yml"]
DB_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class SchemaRestoreError(Exception):
    """Base exception for schema restore failures."""


class SchemaRestoreUnavailable(SchemaRestoreError):
    """Raised when a schema restore is not possible in the current environment."""


@dataclass(frozen=True)
class SchemaArtifact:
    id: int
    name: str
    expired: bool
    size_in_bytes: int
    archive_download_url: str
    head_sha: str
    created_at: str


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "hogli.yaml").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _find_repo_root()


def _resolve_repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _run(command: list[str], *, env: Mapping[str, str] | None = None) -> None:
    subprocess.run(
        command,
        cwd=REPO_ROOT,
        env={**os.environ, **dict(env or {})},
        check=True,
    )


def _validate_db_identifier(target_db: str) -> str:
    if not DB_IDENTIFIER_RE.fullmatch(target_db):
        raise SchemaRestoreError(f"target database must be a simple SQL identifier (got: {target_db})")
    return target_db


def _validate_gzip(path: Path) -> None:
    try:
        with gzip.open(path, "rb") as source:
            while source.read(1024 * 1024):
                pass
    except OSError as exc:
        raise SchemaRestoreError(f"schema dump is not valid gzip: {path}") from exc


def _run_psql_with_gzip_input(gzip_path: Path, target_db: str) -> None:
    command = [*DOCKER_COMPOSE, "exec", "-T", "db", "psql", "-q", "-U", "posthog", target_db]
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        stdin=subprocess.PIPE,
    )
    assert process.stdin is not None  # stdin=PIPE guarantees this

    try:
        with gzip.open(gzip_path, "rb") as source:
            shutil.copyfileobj(source, process.stdin)
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass

    returncode = process.wait()
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, command)


def _psql_admin(sql: str) -> None:
    """Run a one-shot SQL statement against the postgres maintenance database."""
    _run([*DOCKER_COMPOSE, "exec", "-T", "db", "psql", "-U", "posthog", "postgres", "-c", sql])


def _ensure_migration_defaults(target_db: str) -> None:
    _run(
        ["python", "manage.py", "ensure_migration_defaults"],
        env={"DATABASE_URL": f"postgres://posthog:posthog@localhost:5432/{target_db}"},
    )


def restore_schema_dump(
    *,
    target_db: str,
    recreate: bool,
    schema_path: Path = LOCAL_SCHEMA_PATH,
    ensure_defaults: bool = True,
) -> None:
    target_db = _validate_db_identifier(target_db)
    resolved_schema_path = _resolve_repo_path(schema_path)
    if not resolved_schema_path.is_file():
        raise SchemaRestoreError(f"no schema at {schema_path}; run db:download-schema first")

    _validate_gzip(resolved_schema_path)

    if recreate:
        _psql_admin(f"DROP DATABASE IF EXISTS {target_db};")
        _psql_admin(f"CREATE DATABASE {target_db};")

    _run_psql_with_gzip_input(resolved_schema_path, target_db)

    if ensure_defaults:
        _ensure_migration_defaults(target_db)

    click.echo(f"Restored {target_db} from {schema_path}")


def _github_token() -> str | None:
    for env_var in ("GH_TOKEN", "GITHUB_TOKEN"):
        token = os.environ.get(env_var)
        if token:
            return token

    gh_path = shutil.which("gh")
    if gh_path is None:
        return None

    try:
        result = subprocess.run(
            [gh_path, "auth", "token"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    token = result.stdout.strip()
    if result.returncode == 0 and token:
        return token
    return None


def _github_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _artifact_from_api(raw: Mapping[str, object]) -> SchemaArtifact | None:
    workflow_run = raw.get("workflow_run")
    if not isinstance(workflow_run, Mapping):
        return None

    artifact_id = raw.get("id")
    size_in_bytes = raw.get("size_in_bytes")
    expired = raw.get("expired")
    name = raw.get("name")
    archive_download_url = raw.get("archive_download_url")
    head_sha = workflow_run.get("head_sha")
    created_at = raw.get("created_at")

    if not isinstance(artifact_id, int):
        return None
    if not isinstance(size_in_bytes, int):
        return None
    if not isinstance(expired, bool):
        return None
    if not isinstance(name, str):
        return None
    if not isinstance(archive_download_url, str):
        return None
    if not isinstance(head_sha, str):
        return None
    if not isinstance(created_at, str):
        return None

    return SchemaArtifact(
        id=artifact_id,
        name=name,
        expired=expired,
        size_in_bytes=size_in_bytes,
        archive_download_url=archive_download_url,
        head_sha=head_sha,
        created_at=created_at,
    )


def _parse_github_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _is_git_ancestor(base_sha: str, head_ref: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_sha, head_ref],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def select_newest_compatible_artifact(
    artifacts: Iterable[SchemaArtifact],
    *,
    head_ref: str = "HEAD",
    is_ancestor: Callable[[str, str], bool] = _is_git_ancestor,
) -> SchemaArtifact | None:
    candidates = [
        artifact
        for artifact in artifacts
        if artifact.name == SCHEMA_ARTIFACT_NAME
        and not artifact.expired
        and artifact.size_in_bytes > MIN_SCHEMA_ARTIFACT_BYTES
        and artifact.head_sha
    ]
    candidates.sort(key=lambda artifact: (_parse_github_datetime(artifact.created_at), artifact.id), reverse=True)

    for artifact in candidates:
        if is_ancestor(artifact.head_sha, head_ref):
            return artifact

    return None


def fetch_schema_artifacts(*, token: str | None, session: requests.Session | None = None) -> list[SchemaArtifact]:
    http = session or requests.Session()
    artifacts: list[SchemaArtifact] = []
    page = 1

    while True:
        response = http.get(
            f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/artifacts",
            params={"name": SCHEMA_ARTIFACT_NAME, "per_page": 100, "page": page},
            headers=_github_headers(token),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise SchemaRestoreError("GitHub artifacts API returned an unexpected payload")

        raw_artifacts = payload.get("artifacts")
        if not isinstance(raw_artifacts, list):
            raise SchemaRestoreError("GitHub artifacts API returned no artifact list")

        for raw_artifact in raw_artifacts:
            if isinstance(raw_artifact, Mapping):
                artifact = _artifact_from_api(raw_artifact)
                if artifact is not None:
                    artifacts.append(artifact)

        if "next" not in response.links:
            break
        page += 1

    return artifacts


def download_schema_artifact(
    artifact: SchemaArtifact,
    *,
    token: str | None,
    destination: Path = LOCAL_SCHEMA_PATH,
    session: requests.Session | None = None,
) -> None:
    if token is None:
        raise SchemaRestoreUnavailable("no GitHub token found; run `gh auth login` or set GH_TOKEN")

    http = session or requests.Session()
    response = http.get(
        artifact.archive_download_url,
        headers=_github_headers(token),
        stream=True,
        timeout=60,
    )
    response.raise_for_status()

    resolved_destination = _resolve_repo_path(destination)
    resolved_destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="migrated-schema-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        archive_path = temp_dir / "artifact.zip"
        with open(archive_path, "wb") as archive_file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    archive_file.write(chunk)

        with zipfile.ZipFile(archive_path) as archive:
            schema_members = [
                member
                for member in archive.namelist()
                if Path(member).name == SCHEMA_DUMP_NAME and not member.endswith("/")
            ]
            if not schema_members:
                raise SchemaRestoreError(f"artifact {artifact.id} does not contain {SCHEMA_DUMP_NAME}")

            partial_destination = resolved_destination.with_suffix(resolved_destination.suffix + ".tmp")
            with archive.open(schema_members[0]) as source, open(partial_destination, "wb") as destination_file:
                shutil.copyfileobj(source, destination_file)
            partial_destination.replace(resolved_destination)

    click.echo(f"Downloaded schema artifact {artifact.id} to {destination}")


def download_latest_compatible_schema(
    *,
    destination: Path = LOCAL_SCHEMA_PATH,
    head_ref: str = "HEAD",
    session: requests.Session | None = None,
) -> SchemaArtifact:
    token = _github_token()
    artifacts = fetch_schema_artifacts(token=token, session=session)
    artifact = select_newest_compatible_artifact(artifacts, head_ref=head_ref)
    if artifact is None:
        raise SchemaRestoreUnavailable(f"no compatible {SCHEMA_ARTIFACT_NAME} artifact found")

    download_schema_artifact(artifact, token=token, destination=destination, session=session)
    return artifact


def is_database_empty(target_db: str) -> bool:
    target_db = _validate_db_identifier(target_db)
    query = """
        SELECT COUNT(*)
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname !~ '^pg_toast'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f');
    """
    result = subprocess.run(
        [*DOCKER_COMPOSE, "exec", "-T", "db", "psql", "-qAt", "-U", "posthog", target_db, "-c", query],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SchemaRestoreError(result.stderr.strip() or f"failed to inspect database {target_db}")

    try:
        relation_count = int(result.stdout.strip() or "0")
    except ValueError as exc:
        raise SchemaRestoreError(f"unexpected relation count from database {target_db}: {result.stdout!r}") from exc

    return relation_count == 0


def restore_schema_if_fresh(*, target_db: str, mode: ArtifactMode) -> bool:
    if mode == "off":
        click.echo("Schema restore disabled; running migrations normally")
        return False

    if not is_database_empty(target_db):
        click.echo(f"Database {target_db} is not empty; running migrations normally")
        return False

    click.echo(f"Database {target_db} is empty; restoring latest compatible schema before migrations")
    download_latest_compatible_schema()
    restore_schema_dump(target_db=target_db, recreate=False, ensure_defaults=True)
    return True


def _handle_restore_failure(exc: Exception, *, mode: ArtifactMode) -> None:
    if mode == "auto":
        click.echo(f"Schema restore skipped; falling back to migrations: {exc}", err=True)
        return
    raise click.ClickException(str(exc)) from exc


def _effective_mode(mode: str | None) -> ArtifactMode:
    value = mode or os.environ.get("POSTHOG_SCHEMA_RESTORE_IN_DEV", "auto")
    if value not in {"off", "auto", "on"}:
        raise click.UsageError("mode must be one of: off, auto, on")
    return cast(ArtifactMode, value)


def _create_postgres_backup() -> Path:
    backup_dir = REPO_ROOT / ".postgres-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"posthog_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql.gz"
    command = [*DOCKER_COMPOSE, "exec", "-T", "db", "pg_dumpall", "--clean", "-U", "posthog"]
    dump = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
    )
    assert dump.stdout is not None  # stdout=PIPE guarantees this

    try:
        with open(backup_file, "wb") as raw_backup, gzip.GzipFile(fileobj=raw_backup, mode="wb") as compressed_backup:
            shutil.copyfileobj(dump.stdout, compressed_backup)
    except Exception:
        dump.kill()
        dump.wait()
        backup_file.unlink(missing_ok=True)
        raise
    finally:
        dump.stdout.close()

    returncode = dump.wait()
    if returncode != 0:
        backup_file.unlink(missing_ok=True)
        raise subprocess.CalledProcessError(returncode, command)

    click.echo(f"Backup saved to: {backup_file.relative_to(REPO_ROOT)}")
    return backup_file


def _confirm_restore_schema(yes: bool) -> bool:
    if yes:
        return True

    click.echo()
    click.secho("Warning: this command may overwrite your local PostgreSQL schema.", fg="yellow", bold=True)
    click.echo("A backup will be created before restoring.")
    click.echo()
    if click.confirm("Are you sure you want to continue?", default=False):
        return True

    click.secho("Aborted.", fg="red")
    return False


@click.command(name="db:download-schema", help="Download the latest compatible pre-migrated schema artifact")
def db_download_schema() -> None:
    try:
        download_latest_compatible_schema()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


def _recreate_test_db() -> None:
    try:
        restore_schema_dump(target_db=os.environ.get("TARGET_DB", "test_posthog"), recreate=True, ensure_defaults=True)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@click.command(
    name="db:restore-test-db", help="Restore a fresh test database from .postgres-backups/schema-latest.sql.gz"
)
def db_restore_test_db() -> None:
    _recreate_test_db()


@click.command(name="db:restore-schema-fresh", help="Alias for db:restore-test-db")
def db_restore_schema_fresh() -> None:
    _recreate_test_db()


@click.command(
    name="db:restore-schema-if-fresh", help="Restore schema into an empty local dev database before migrations"
)
@click.option(
    "--mode",
    type=click.Choice(["off", "auto", "on"]),
    default=None,
    help="Restore mode. Defaults to POSTHOG_SCHEMA_RESTORE_IN_DEV or auto.",
)
@click.option("--target-db", default="posthog", show_default=True, help="Database to inspect and restore")
def db_restore_schema_if_fresh(mode: str | None, target_db: str) -> None:
    effective_mode = _effective_mode(mode)
    try:
        restore_schema_if_fresh(target_db=target_db, mode=effective_mode)
    except Exception as exc:
        _handle_restore_failure(exc, mode=effective_mode)


@click.command(
    name="db:restore-schema", help="Fetch and restore the latest compatible schema into the local posthog database"
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def db_restore_schema(yes: bool) -> None:
    if not _confirm_restore_schema(yes):
        return

    try:
        download_latest_compatible_schema()
        _create_postgres_backup()
        restore_schema_dump(target_db="posthog", recreate=False, ensure_defaults=False)
        _run([str(REPO_ROOT / "bin" / "migrate")])
        _ensure_migration_defaults("posthog")
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
