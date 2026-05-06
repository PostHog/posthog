from __future__ import annotations

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


def test_unset_env_var_resolves_to_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTHOG_SCHEMA_RESTORE", raising=False)
    assert db_schema._normalize_mode(None) == "off"


def test_invalid_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POSTHOG_SCHEMA_RESTORE", raising=False)
    with pytest.raises(click.ClickException):
        db_schema._normalize_mode("maybe")


def test_command_failure_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_download() -> db_schema.SchemaArtifact:
        raise click.ClickException("download failed")

    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: True)
    monkeypatch.setattr(db_schema, "_ensure_schema_downloaded", fail_download)

    auto_result = runner.invoke(cli, ["db:restore-schema-if-fresh", "--mode=auto"])
    on_result = runner.invoke(cli, ["db:restore-schema-if-fresh", "--mode=on"])

    assert auto_result.exit_code == 0
    assert "falling back to normal migrations" in auto_result.output
    assert "download failed" in auto_result.output
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


def test_restore_schema_delegates_to_hogli_db_restore_test_db(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(db_schema.subprocess, "run", fake_run)

    db_schema._restore_schema()

    args = captured["args"]
    kwargs = captured["kwargs"]
    assert isinstance(args, list)
    assert isinstance(kwargs, dict)
    assert args[-1] == "db:restore-test-db"
    assert args[0].endswith("/bin/hogli")
    assert kwargs["env"]["TARGET_DB"] == "posthog"
    assert kwargs["cwd"] == db_schema.REPO_ROOT
    assert kwargs["check"] is False


def test_restore_schema_surfaces_subprocess_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="hogli blew up")

    monkeypatch.setattr(db_schema.subprocess, "run", fake_run)

    with pytest.raises(click.ClickException) as excinfo:
        db_schema._restore_schema()
    assert "hogli blew up" in excinfo.value.message


def test_migrate_hook_uses_only_posthog_schema_restore() -> None:
    migrate_script = (db_schema.REPO_ROOT / "bin" / "migrate").read_text()

    assert '"$SCRIPT_DIR/hogli" db:restore-schema-if-fresh' in migrate_script
    assert '"${POSTHOG_SCHEMA_RESTORE:-off}"' in migrate_script
    assert "CODER_WORKSPACE_ID" not in migrate_script
    assert "schema_restore_mode()" not in migrate_script
    assert "prepare_schema_restore_github_token" not in migrate_script


def test_bin_start_opts_into_auto_mode() -> None:
    start_script = (db_schema.REPO_ROOT / "bin" / "start").read_text()

    assert "POSTHOG_SCHEMA_RESTORE=${POSTHOG_SCHEMA_RESTORE:-auto}" in start_script
