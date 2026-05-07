from __future__ import annotations

import gzip
import subprocess
from pathlib import Path
from typing import Any

import pytest

from click.testing import CliRunner
from hogli.cli import cli
from hogli_commands import db_schema

runner = CliRunner()


def _artifact(
    artifact_id: int,
    head_sha: str,
    created_at: str,
    *,
    expired: bool = False,
    size_in_bytes: int = db_schema.MIN_SCHEMA_ARTIFACT_BYTES + 1,
    name: str = db_schema.SCHEMA_ARTIFACT_NAME,
) -> db_schema.SchemaArtifact:
    return db_schema.SchemaArtifact(
        id=artifact_id,
        name=name,
        expired=expired,
        size_in_bytes=size_in_bytes,
        archive_download_url=f"https://api.github.com/artifacts/{artifact_id}/zip",
        head_sha=head_sha,
        created_at=created_at,
    )


def _write_schema(path: Path) -> None:
    with gzip.open(path, "wb") as schema:
        schema.write(b"SELECT 1;\n")


def test_select_newest_ancestor_artifact() -> None:
    artifacts = [
        _artifact(1, "older", "2026-01-01T00:00:00Z"),
        _artifact(2, "newer", "2026-01-02T00:00:00Z"),
    ]

    selected = db_schema.select_newest_compatible_artifact(
        artifacts,
        is_ancestor=lambda base_sha, head_ref: base_sha in {"older", "newer"},
    )

    assert selected == artifacts[1]


def test_select_skips_newer_non_ancestor_artifact() -> None:
    artifacts = [
        _artifact(1, "older", "2026-01-01T00:00:00Z"),
        _artifact(2, "newer", "2026-01-02T00:00:00Z"),
    ]

    selected = db_schema.select_newest_compatible_artifact(
        artifacts,
        is_ancestor=lambda base_sha, head_ref: base_sha == "older",
    )

    assert selected == artifacts[0]


@pytest.mark.parametrize(
    "artifact",
    [
        _artifact(1, "sha", "2026-01-01T00:00:00Z", expired=True),
        _artifact(1, "sha", "2026-01-01T00:00:00Z", size_in_bytes=100),
        _artifact(1, "", "2026-01-01T00:00:00Z"),
        _artifact(1, "sha", "2026-01-01T00:00:00Z", name="other"),
    ],
)
def test_select_ignores_invalid_artifacts(artifact: db_schema.SchemaArtifact) -> None:
    assert (
        db_schema.select_newest_compatible_artifact(
            [artifact],
            is_ancestor=lambda base_sha, head_ref: True,
        )
        is None
    )


def test_restore_schema_if_fresh_restores_empty_db(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    monkeypatch.setattr(
        db_schema, "is_database_empty", lambda target_db: calls.append(("empty", {"target_db": target_db})) or True
    )
    monkeypatch.setattr(
        db_schema,
        "download_latest_compatible_schema",
        lambda: calls.append(("download", {})) or _artifact(1, "sha", "2026-01-01T00:00:00Z"),
    )
    monkeypatch.setattr(
        db_schema,
        "restore_schema_dump",
        lambda **kwargs: calls.append(("restore", kwargs)),
    )

    result = db_schema.restore_schema_if_fresh(target_db="posthog", mode="auto")

    assert result is True
    assert calls == [
        ("empty", {"target_db": "posthog"}),
        ("download", {}),
        ("restore", {"target_db": "posthog", "recreate": False, "ensure_defaults": True}),
    ]


def test_restore_schema_if_fresh_skips_non_empty_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_schema, "is_database_empty", lambda target_db: False)
    monkeypatch.setattr(
        db_schema,
        "download_latest_compatible_schema",
        lambda: pytest.fail("download should not run"),
    )

    result = db_schema.restore_schema_if_fresh(target_db="posthog", mode="auto")

    assert result is False


def test_restore_schema_dump_recreate_drops_and_creates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema_path = tmp_path / "schema.sql.gz"
    _write_schema(schema_path)
    commands: list[list[str]] = []
    restored: list[tuple[Path, str]] = []
    defaults: list[str] = []

    monkeypatch.setattr(db_schema, "_run", lambda command, env=None: commands.append(command))
    monkeypatch.setattr(
        db_schema,
        "_run_psql_with_gzip_input",
        lambda gzip_path, target_db: restored.append((gzip_path, target_db)),
    )
    monkeypatch.setattr(db_schema, "_ensure_migration_defaults", lambda target_db: defaults.append(target_db))

    db_schema.restore_schema_dump(target_db="test_posthog", recreate=True, schema_path=schema_path)

    assert any("DROP DATABASE IF EXISTS test_posthog;" in command for call in commands for command in call)
    assert any("CREATE DATABASE test_posthog;" in command for call in commands for command in call)
    assert restored == [(schema_path, "test_posthog")]
    assert defaults == ["test_posthog"]


def test_restore_schema_dump_without_recreate_does_not_drop_posthog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_path = tmp_path / "schema.sql.gz"
    _write_schema(schema_path)
    commands: list[list[str]] = []

    monkeypatch.setattr(db_schema, "_run", lambda command, env=None: commands.append(command))
    monkeypatch.setattr(db_schema, "_run_psql_with_gzip_input", lambda gzip_path, target_db: None)
    monkeypatch.setattr(db_schema, "_ensure_migration_defaults", lambda target_db: None)

    db_schema.restore_schema_dump(target_db="posthog", recreate=False, schema_path=schema_path)

    assert not any("DROP DATABASE" in command for call in commands for command in call)
    assert not any("CREATE DATABASE" in command for call in commands for command in call)


def test_restore_schema_if_fresh_auto_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_schema, "is_database_empty", lambda target_db: True)
    monkeypatch.setattr(
        db_schema,
        "download_latest_compatible_schema",
        lambda: (_ for _ in ()).throw(db_schema.SchemaRestoreUnavailable("no compatible artifact")),
    )

    result = runner.invoke(db_schema.db_restore_schema_if_fresh, ["--mode=auto"])

    assert result.exit_code == 0
    assert "falling back to migrations" in result.output


def test_restore_schema_if_fresh_on_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_schema, "is_database_empty", lambda target_db: True)
    monkeypatch.setattr(
        db_schema,
        "download_latest_compatible_schema",
        lambda: (_ for _ in ()).throw(db_schema.SchemaRestoreUnavailable("no compatible artifact")),
    )

    result = runner.invoke(db_schema.db_restore_schema_if_fresh, ["--mode=on"])

    assert result.exit_code == 1
    assert "no compatible artifact" in result.output


def test_restore_schema_if_fresh_auto_falls_back_on_restore_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_schema, "is_database_empty", lambda target_db: True)
    monkeypatch.setattr(
        db_schema, "download_latest_compatible_schema", lambda: _artifact(1, "sha", "2026-01-01T00:00:00Z")
    )
    monkeypatch.setattr(
        db_schema,
        "restore_schema_dump",
        lambda **kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, ["psql"])),
    )

    result = runner.invoke(db_schema.db_restore_schema_if_fresh, ["--mode=auto"])

    assert result.exit_code == 0
    assert "falling back to migrations" in result.output


def test_restore_schema_if_fresh_off_skips_without_database_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_schema, "is_database_empty", lambda target_db: pytest.fail("database check should not run"))

    result = runner.invoke(db_schema.db_restore_schema_if_fresh, ["--mode=off"])

    assert result.exit_code == 0
    assert "Schema restore disabled" in result.output


def test_restore_test_db_command_exists() -> None:
    result = runner.invoke(cli, ["db:restore-test-db", "--help"])

    assert result.exit_code == 0
    assert "Restore a fresh test database" in result.output


def test_restore_schema_fresh_command_exists_and_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv("TARGET_DB", "posthog_e2e_test")
    monkeypatch.setattr(db_schema, "restore_schema_dump", lambda **kwargs: calls.append(kwargs))

    result = runner.invoke(db_schema.db_restore_schema_fresh)

    assert result.exit_code == 0
    assert calls == [{"target_db": "posthog_e2e_test", "recreate": True, "ensure_defaults": True}]


@pytest.mark.parametrize("mode", ["off", "auto", "on"])
def test_restore_schema_if_fresh_mode_parses(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(db_schema, "restore_schema_if_fresh", lambda **kwargs: calls.append(kwargs) or False)

    result = runner.invoke(cli, ["db:restore-schema-if-fresh", f"--mode={mode}"])

    assert result.exit_code == 0
    assert calls == [{"target_db": "posthog", "mode": mode}]
