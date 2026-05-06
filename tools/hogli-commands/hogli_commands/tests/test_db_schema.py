from __future__ import annotations

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
    """Happy path: orchestration runs all the gates and delegates to the restore."""
    restored: list[bool] = []

    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: True)
    monkeypatch.setattr(db_schema, "_fetch_schema_artifact", _artifact)
    monkeypatch.setattr(db_schema, "_schema_sha_is_ancestor", lambda sha: True)
    monkeypatch.setattr(db_schema, "_restore_schema", lambda: restored.append(True))

    assert db_schema.restore_schema_if_fresh("auto") is True
    assert restored == [True]


def test_auto_falls_back_silently_on_failure_but_on_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mode contract: auto eats failures, on surfaces them."""

    def fail() -> db_schema.SchemaArtifact:
        raise click.ClickException("download failed")

    monkeypatch.setattr(db_schema, "_database_is_fresh", lambda: True)
    monkeypatch.setattr(db_schema, "_fetch_schema_artifact", fail)

    auto_result = runner.invoke(cli, ["db:restore-schema-if-fresh", "--mode=auto"])
    on_result = runner.invoke(cli, ["db:restore-schema-if-fresh", "--mode=on"])

    assert auto_result.exit_code == 0
    assert "falling back to normal migrations" in auto_result.output
    assert "download failed" in auto_result.output
    assert on_result.exit_code != 0
    assert "download failed" in on_result.output
