from __future__ import annotations

import gzip
import zipfile
import subprocess
from io import BytesIO
from pathlib import Path

import pytest

import click
from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands import db_schema

runner = CliRunner()


def test_auto_mode_skips_outside_coder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODER_WORKSPACE_ID", raising=False)
    monkeypatch.delenv("CODER_WORKSPACE_NAME", raising=False)
    monkeypatch.setattr(
        db_schema,
        "_database_is_fresh",
        lambda: pytest.fail("_database_is_fresh should not be called"),
    )

    assert db_schema.restore_schema_if_fresh("auto") is False


def test_auto_mode_runs_inside_devbox(monkeypatch: pytest.MonkeyPatch) -> None:
    restored: list[bool] = []
    artifact = db_schema.SchemaArtifact(
        id=1,
        workflow_run_id=2,
        head_sha="abc123",
        archive_download_url="https://example.com/artifact.zip",
        created_at="2026-01-01T00:00:00Z",
    )

    monkeypatch.setenv("CODER_WORKSPACE_ID", "workspace-id")
    monkeypatch.setenv("CODER_WORKSPACE_NAME", "devbox-test-user")
    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: True)
    monkeypatch.setattr(db_schema, "_ensure_schema_downloaded", lambda: artifact)
    monkeypatch.setattr(db_schema, "_schema_sha_is_ancestor", lambda sha: True)
    monkeypatch.setattr(db_schema, "_restore_schema", lambda: restored.append(True))

    assert db_schema.restore_schema_if_fresh("auto") is True
    assert restored == [True]


def test_explicit_on_allows_local_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    restored: list[bool] = []
    artifact = db_schema.SchemaArtifact(
        id=1,
        workflow_run_id=2,
        head_sha="abc123",
        archive_download_url="https://example.com/artifact.zip",
        created_at="2026-01-01T00:00:00Z",
    )

    monkeypatch.delenv("CODER_WORKSPACE_ID", raising=False)
    monkeypatch.delenv("CODER_WORKSPACE_NAME", raising=False)
    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: True)
    monkeypatch.setattr(db_schema, "_ensure_schema_downloaded", lambda: artifact)
    monkeypatch.setattr(db_schema, "_schema_sha_is_ancestor", lambda sha: True)
    monkeypatch.setattr(db_schema, "_restore_schema", lambda: restored.append(True))

    assert db_schema.restore_schema_if_fresh("on") is True
    assert restored == [True]


@pytest.mark.parametrize("mode", ["0", "false", "off", "no"])
def test_off_mode_skips(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setattr(
        db_schema,
        "_database_is_fresh",
        lambda: pytest.fail("_database_is_fresh should not be called"),
    )

    assert db_schema.restore_schema_if_fresh(mode) is False


def test_non_fresh_database_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: False)
    monkeypatch.setattr(
        db_schema,
        "_ensure_schema_downloaded",
        lambda: pytest.fail("_ensure_schema_downloaded should not be called"),
    )

    assert db_schema.restore_schema_if_fresh("on") is False


def test_newer_schema_skips_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = db_schema.SchemaArtifact(
        id=1,
        workflow_run_id=2,
        head_sha="abc123",
        archive_download_url="https://example.com/artifact.zip",
        created_at="2026-01-01T00:00:00Z",
    )

    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: True)
    monkeypatch.setattr(db_schema, "_ensure_schema_downloaded", lambda: artifact)
    monkeypatch.setattr(db_schema, "_schema_sha_is_ancestor", lambda sha: False)
    monkeypatch.setattr(db_schema, "_restore_schema", lambda: pytest.fail("_restore_schema should not be called"))

    assert db_schema.restore_schema_if_fresh("on") is False


def test_auto_command_falls_back_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODER_WORKSPACE_ID", "workspace-id")
    monkeypatch.setenv("CODER_WORKSPACE_NAME", "devbox-test-user")
    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: True)
    monkeypatch.setattr(
        db_schema,
        "_ensure_schema_downloaded",
        lambda: (_ for _ in ()).throw(click.ClickException("download failed")),
    )

    result = runner.invoke(cli, ["db:restore-schema-if-fresh"])

    assert result.exit_code == 0
    assert "falling back to normal migrations" in result.output


def test_on_command_surfaces_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: True)
    monkeypatch.setattr(
        db_schema,
        "_ensure_schema_downloaded",
        lambda: (_ for _ in ()).throw(click.ClickException("download failed")),
    )

    result = runner.invoke(cli, ["db:restore-schema-if-fresh", "--mode=on"])

    assert result.exit_code != 0
    assert "download failed" in result.output


def test_github_token_prefers_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")

    assert db_schema._github_token() == "gh-token"


def test_github_token_falls_back_to_coder_external_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_token_from_command(args: list[str]) -> str | None:
        calls.append(args)
        if args[:3] == ["coder", "external-auth", "access-token"]:
            return "coder-token"
        return None

    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("CODER_WORKSPACE_ID", "workspace-id")
    monkeypatch.setenv("CODER_WORKSPACE_NAME", "devbox-test-user")
    monkeypatch.setattr(db_schema, "_token_from_command", fake_token_from_command)

    assert db_schema._github_token() == "coder-token"
    assert ["coder", "external-auth", "access-token", "primary-github"] in calls


def test_download_schema_artifact_writes_schema_and_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema_path = tmp_path / "schema-latest.sql.gz"
    metadata_path = tmp_path / "schema-latest.json"
    artifact = db_schema.SchemaArtifact(
        id=123,
        workflow_run_id=456,
        head_sha="abc123",
        archive_download_url="https://example.com/artifact.zip",
        created_at="2026-01-01T00:00:00Z",
    )

    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as artifact_zip:
        artifact_zip.writestr("schema.sql.gz", b"schema-bytes")

    monkeypatch.setattr(db_schema, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(db_schema, "SCHEMA_PATH", schema_path)
    monkeypatch.setattr(db_schema, "SCHEMA_METADATA_PATH", metadata_path)
    monkeypatch.setattr(db_schema, "_github_request", lambda url, token: archive_buffer.getvalue())

    db_schema._download_schema_artifact(artifact, "token")

    assert schema_path.read_bytes() == b"schema-bytes"
    assert '"artifact_id": 123' in metadata_path.read_text()
    assert '"head_sha": "abc123"' in metadata_path.read_text()


def test_restore_schema_uses_transactional_psql(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema_sql = b"CREATE TABLE example(id integer);\n"
    schema_path = tmp_path / "schema-latest.sql.gz"
    stream_calls: list[tuple[list[str], bytes | None]] = []
    capture_calls: list[tuple[list[str], int]] = []

    def fake_run_stream(args: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        stream_calls.append((args, input_bytes))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")

    def fake_run_capture(
        args: list[str], *, input_text: str | None = None, timeout: int = 20
    ) -> subprocess.CompletedProcess[str]:
        capture_calls.append((args, timeout))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    schema_path.write_bytes(gzip.compress(schema_sql))
    monkeypatch.setattr(db_schema, "SCHEMA_PATH", schema_path)
    monkeypatch.setattr(db_schema, "_run_stream", fake_run_stream)
    monkeypatch.setattr(db_schema, "_run_capture", fake_run_capture)

    db_schema._restore_schema()

    assert stream_calls == [
        (
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
            schema_sql,
        )
    ]
    assert capture_calls == [(["python", "manage.py", "ensure_migration_defaults"], 120)]


def test_migrate_invokes_schema_restore_before_postgres_migrations() -> None:
    migrate_script = (db_schema.REPO_ROOT / "bin" / "migrate").read_text()

    restore_index = migrate_script.index('"$SCRIPT_DIR/hogli" db:restore-schema-if-fresh')
    migrate_index = migrate_script.index("MIGRATE_MAX_RETRIES")

    assert restore_index < migrate_index


def test_migrate_restore_is_debug_only() -> None:
    migrate_script = (db_schema.REPO_ROOT / "bin" / "migrate").read_text()

    assert 'if [ "${DEBUG:-0}" = "1" ]; then' in migrate_script


def test_schema_sha_is_ancestor_uses_git_merge_base(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run_capture(
        args: list[str], *, input_text: str | None = None, timeout: int = 20
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(db_schema, "_run_capture", fake_run_capture)

    assert db_schema._schema_sha_is_ancestor("abc123") is True
    assert calls == [["git", "merge-base", "--is-ancestor", "abc123", "HEAD"]]
