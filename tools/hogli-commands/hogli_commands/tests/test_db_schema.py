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


def _artifact() -> db_schema.SchemaArtifact:
    return db_schema.SchemaArtifact(
        id=1,
        workflow_run_id=2,
        head_sha="abc123",
        archive_download_url="https://example.com/artifact.zip",
        created_at="2026-01-01T00:00:00Z",
    )


def test_auto_mode_restores_when_database_is_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    restored: list[bool] = []

    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: True)
    monkeypatch.setattr(db_schema, "_ensure_schema_downloaded", _artifact)
    monkeypatch.setattr(db_schema, "_schema_sha_is_ancestor", lambda sha: True)
    monkeypatch.setattr(db_schema, "_restore_schema", lambda: restored.append(True))

    assert db_schema.restore_schema_if_fresh("auto") is True
    assert restored == [True]


def test_off_mode_skips_without_touching_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        db_schema,
        "_database_is_fresh",
        lambda: pytest.fail("_database_is_fresh should not be called"),
    )

    assert db_schema.restore_schema_if_fresh("off") is False


def test_command_failure_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_download() -> db_schema.SchemaArtifact:
        raise click.ClickException("download failed")

    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: True)
    monkeypatch.setattr(db_schema, "_ensure_schema_downloaded", fail_download)

    auto_result = runner.invoke(cli, ["db:restore-schema-if-fresh", "--mode=auto"])
    on_result = runner.invoke(cli, ["db:restore-schema-if-fresh", "--mode=on"])

    assert auto_result.exit_code == 0
    assert "falling back to normal migrations" in auto_result.output
    assert on_result.exit_code != 0
    assert "download failed" in on_result.output


def test_github_token_uses_standard_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setattr(db_schema, "_token_from_command", lambda args: pytest.fail("gh should not be called"))

    assert db_schema._github_token() == "gh-token"


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


def test_migrate_hook_enables_auto_only_for_coder_env() -> None:
    migrate_script = (db_schema.REPO_ROOT / "bin" / "migrate").read_text()

    restore_index = migrate_script.index('"$SCRIPT_DIR/hogli" db:restore-schema-if-fresh --mode="$SCHEMA_RESTORE_MODE"')
    migrate_index = migrate_script.index("MIGRATE_MAX_RETRIES")

    assert "schema_restore_mode()" in migrate_script
    assert 'if [ -n "${POSTHOG_SCHEMA_RESTORE+x}" ]; then' in migrate_script
    assert 'elif [ -n "${CODER_WORKSPACE_ID:-}" ]; then' in migrate_script
    assert 'echo "auto"' in migrate_script
    assert "prepare_schema_restore_github_token" in migrate_script
    assert "coder external-auth access-token primary-github" in migrate_script
    assert restore_index < migrate_index
