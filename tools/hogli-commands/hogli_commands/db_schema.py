"""PostgreSQL schema cache helpers for local development."""

from __future__ import annotations

import os
import gzip
import json
import shutil
import zipfile
import tempfile
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import cast

import click
from hogli.cli import cli
from hogli.manifest import REPO_ROOT

ARTIFACT_API_URL = "https://api.github.com/repos/PostHog/posthog/actions/artifacts?name=migrated-schema&per_page=10"
BACKUP_DIR = REPO_ROOT / ".postgres-backups"
SCHEMA_PATH = BACKUP_DIR / "schema-latest.sql.gz"
SCHEMA_METADATA_PATH = BACKUP_DIR / "schema-latest.json"
MIN_SCHEMA_ARTIFACT_SIZE_BYTES = 10_000
CODER_GITHUB_EXTERNAL_AUTH_ID = "primary-github"


@dataclass(frozen=True)
class SchemaArtifact:
    id: int
    workflow_run_id: int
    head_sha: str
    archive_download_url: str
    created_at: str


def _normalize_mode(raw_mode: str | None) -> str:
    mode = (raw_mode or os.environ.get("POSTHOG_SCHEMA_RESTORE") or "auto").strip().lower()
    if mode in {"auto", ""}:
        return "auto"
    if mode in {"1", "true", "yes", "on"}:
        return "on"
    if mode in {"0", "false", "no", "off"}:
        return "off"
    raise click.ClickException("POSTHOG_SCHEMA_RESTORE must be auto, on, or off")


def _is_coder_devbox() -> bool:
    workspace_id = os.environ.get("CODER_WORKSPACE_ID")
    workspace_name = os.environ.get("CODER_WORKSPACE_NAME", "")
    return bool(workspace_id and workspace_name.startswith("devbox-"))


def _should_attempt_restore(mode: str) -> bool:
    if mode == "off":
        return False
    if mode == "on":
        return True
    return _is_coder_devbox()


def _run_capture(
    args: list[str], *, input_text: str | None = None, timeout: int = 20
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _run_stream(args: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        input=input_bytes,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )


def _psql_scalar(sql: str) -> str:
    result = _run_capture(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "posthog", "-d", "posthog", "-Atc", sql]
    )
    if result.returncode != 0:
        raise click.ClickException(result.stderr.strip() or "Failed to query local Postgres")
    return result.stdout.strip()


def _database_is_fresh() -> bool:
    applied_migrations = _psql_scalar(
        "SELECT CASE WHEN to_regclass('public.django_migrations') IS NULL "
        "THEN 0 ELSE (SELECT count(*) FROM django_migrations) END"
    )
    if applied_migrations and int(applied_migrations) > 0:
        return False

    non_migration_objects = _psql_scalar(
        "SELECT count(*) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' "
        "AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
        "AND c.relname <> 'django_migrations'"
    )
    return int(non_migration_objects or "0") == 0


def _token_from_command(args: list[str]) -> str | None:
    if shutil.which(args[0]) is None:
        return None
    try:
        result = _run_capture(args, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    token = result.stdout.strip()
    return token or None


def _github_token() -> str | None:
    for env_var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if token := os.environ.get(env_var):
            return token

    if token := _token_from_command(["gh", "auth", "token"]):
        return token

    if _is_coder_devbox():
        return _token_from_command(["coder", "external-auth", "access-token", CODER_GITHUB_EXTERNAL_AUTH_ID])

    return None


def _github_request(url: str, token: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "posthog-hogli",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _artifact_from_api_item(item: dict[str, object]) -> SchemaArtifact | None:
    if item.get("expired") is True:
        return None
    if int(cast(int | float | str | None, item.get("size_in_bytes")) or 0) <= MIN_SCHEMA_ARTIFACT_SIZE_BYTES:
        return None

    workflow_run = item.get("workflow_run")
    if not isinstance(workflow_run, dict):
        return None

    artifact_id = item.get("id")
    workflow_run_id = workflow_run.get("id")
    head_sha = workflow_run.get("head_sha")
    archive_download_url = item.get("archive_download_url")
    created_at = item.get("created_at")

    if not (
        isinstance(artifact_id, int)
        and isinstance(workflow_run_id, int)
        and isinstance(head_sha, str)
        and isinstance(archive_download_url, str)
        and isinstance(created_at, str)
    ):
        return None

    return SchemaArtifact(
        id=artifact_id,
        workflow_run_id=workflow_run_id,
        head_sha=head_sha,
        archive_download_url=archive_download_url,
        created_at=created_at,
    )


def _latest_schema_artifact(token: str) -> SchemaArtifact:
    raw = _github_request(ARTIFACT_API_URL, token)
    payload = cast(dict[str, object], json.loads(raw))
    raw_artifacts = payload.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise click.ClickException("GitHub artifacts response was missing artifacts")

    artifacts = [
        artifact
        for item in raw_artifacts
        if isinstance(item, dict)
        if (artifact := _artifact_from_api_item(cast(dict[str, object], item))) is not None
    ]
    if not artifacts:
        raise click.ClickException("No migrated-schema artifact found")

    return max(artifacts, key=lambda artifact: artifact.created_at)


def _download_schema_artifact(artifact: SchemaArtifact, token: str) -> None:
    archive = _github_request(artifact.archive_download_url, token)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(BytesIO(archive)) as artifact_zip:
        try:
            schema_bytes = artifact_zip.read("schema.sql.gz")
        except KeyError:
            raise click.ClickException("migrated-schema artifact did not contain schema.sql.gz")

    with tempfile.NamedTemporaryFile(dir=BACKUP_DIR, delete=False) as tmp_schema:
        tmp_schema.write(schema_bytes)
        tmp_schema_path = Path(tmp_schema.name)
    tmp_schema_path.replace(SCHEMA_PATH)

    metadata = {
        "artifact_id": artifact.id,
        "run_id": artifact.workflow_run_id,
        "head_sha": artifact.head_sha,
        "created_at": artifact.created_at,
        "downloaded_at": datetime.now(UTC).isoformat(),
    }
    SCHEMA_METADATA_PATH.write_text(json.dumps(metadata, indent=2) + "\n")


def _ensure_schema_downloaded() -> SchemaArtifact:
    token = _github_token()
    if not token:
        raise click.ClickException("No GitHub token available for migrated-schema download")

    artifact = _latest_schema_artifact(token)
    if not SCHEMA_PATH.exists():
        _download_schema_artifact(artifact, token)
        return artifact

    if not SCHEMA_METADATA_PATH.exists():
        _download_schema_artifact(artifact, token)
        return artifact

    metadata = cast(dict[str, object], json.loads(SCHEMA_METADATA_PATH.read_text()))
    if metadata.get("artifact_id") != artifact.id:
        _download_schema_artifact(artifact, token)
        return artifact

    return artifact


def _schema_sha_is_ancestor(head_sha: str) -> bool:
    if not head_sha:
        return False

    result = _run_capture(["git", "merge-base", "--is-ancestor", head_sha, "HEAD"])
    return result.returncode == 0


def _restore_schema() -> None:
    try:
        schema_sql = gzip.decompress(SCHEMA_PATH.read_bytes())
    except OSError as err:
        raise click.ClickException(f"Failed to decompress schema: {err}") from err

    restore = _run_stream(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "db",
            "psql",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "--single-transaction",
            "-U",
            "posthog",
            "posthog",
        ],
        input_bytes=schema_sql,
    )
    if restore.returncode != 0:
        raise click.ClickException(restore.stderr.decode(errors="replace").strip() or "Failed to restore schema")

    defaults = _run_capture(["python", "manage.py", "ensure_migration_defaults"], timeout=120)
    if defaults.returncode != 0:
        raise click.ClickException(defaults.stderr.strip() or "Failed to ensure migration defaults")


def restore_schema_if_fresh(mode: str) -> bool:
    normalized_mode = _normalize_mode(mode)
    if not _should_attempt_restore(normalized_mode):
        return False

    if not _database_is_fresh():
        click.echo("[schema-restore] Postgres is not fresh; skipping schema restore.")
        return False

    artifact = _ensure_schema_downloaded()
    if not _schema_sha_is_ancestor(artifact.head_sha):
        click.echo("[schema-restore] Cached schema is newer than this branch; skipping schema restore.")
        return False

    click.echo("[schema-restore] Restoring migrated Postgres schema.")
    _restore_schema()
    click.echo("[schema-restore] Migrated Postgres schema restored.")
    return True


@cli.command(name="db:restore-schema-if-fresh", help="Restore migrated Postgres schema when the local DB is fresh")
@click.option("--mode", default=None, help="auto, on, or off. Defaults to POSTHOG_SCHEMA_RESTORE or auto.")
def restore_schema_if_fresh_command(mode: str | None) -> None:
    """Restore the CI migrated schema only when the local Postgres DB is fresh."""
    normalized_mode = _normalize_mode(mode)
    try:
        restored = restore_schema_if_fresh(normalized_mode)
    except Exception as err:
        if normalized_mode == "auto":
            click.echo(f"[schema-restore] {err}; falling back to normal migrations.")
            return
        if isinstance(err, click.ClickException):
            raise
        raise click.ClickException(str(err))

    if not restored and normalized_mode == "on":
        click.echo("[schema-restore] Nothing restored.")
