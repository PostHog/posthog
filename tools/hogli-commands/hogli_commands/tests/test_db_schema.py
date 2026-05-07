from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any

import pytest

from click.testing import CliRunner
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


@pytest.mark.parametrize(
    "name,content",
    [
        ("not-gzip", b"this is not gzip data"),
        ("empty", b""),
        ("partial-header", b"\x1f\x8b"),
    ],
)
def test_validate_gzip_rejects_corrupt_inputs(tmp_path: Path, name: str, content: bytes) -> None:
    path = tmp_path / f"{name}.sql.gz"
    path.write_bytes(content)
    with pytest.raises(db_schema.SchemaRestoreError):
        db_schema._validate_gzip(path)


def test_validate_gzip_rejects_truncated_stream(tmp_path: Path) -> None:
    full = tmp_path / "good.sql.gz"
    _write_schema(full)
    truncated = tmp_path / "truncated.sql.gz"
    raw = full.read_bytes()
    truncated.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(db_schema.SchemaRestoreError):
        db_schema._validate_gzip(truncated)


@pytest.mark.parametrize(
    "ancestor_shas,expected_index",
    [
        ({"older", "newer"}, 1),
        ({"older"}, 0),
    ],
)
def test_select_newest_compatible_artifact(ancestor_shas: set[str], expected_index: int) -> None:
    artifacts = [
        _artifact(1, "older", "2026-01-01T00:00:00Z"),
        _artifact(2, "newer", "2026-01-02T00:00:00Z"),
    ]

    selected = db_schema.select_newest_compatible_artifact(
        artifacts,
        is_ancestor=lambda base_sha, head_ref: base_sha in ancestor_shas,
    )

    assert selected == artifacts[expected_index]


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


def test_restore_schema_if_fresh_skips_non_empty_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_schema, "is_database_empty", lambda target_db: False)
    monkeypatch.setattr(
        db_schema,
        "download_latest_compatible_schema",
        lambda: pytest.fail("download should not run"),
    )

    assert db_schema.restore_schema_if_fresh(target_db="posthog", mode="auto") is False


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


def test_restore_schema_dump_without_recreate_does_not_drop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema_path = tmp_path / "schema.sql.gz"
    _write_schema(schema_path)
    commands: list[list[str]] = []

    monkeypatch.setattr(db_schema, "_run", lambda command, env=None: commands.append(command))
    monkeypatch.setattr(db_schema, "_run_psql_with_gzip_input", lambda gzip_path, target_db: None)
    monkeypatch.setattr(db_schema, "_ensure_migration_defaults", lambda target_db: None)

    db_schema.restore_schema_dump(target_db="posthog", recreate=False, schema_path=schema_path)

    assert not any("DROP DATABASE" in command for call in commands for command in call)
    assert not any("CREATE DATABASE" in command for call in commands for command in call)


@pytest.mark.parametrize(
    "mode,expected_exit,expected_output",
    [
        ("auto", 0, "falling back to migrations"),
        ("on", 1, "no compatible artifact"),
    ],
)
def test_restore_schema_if_fresh_handles_unavailable_artifact(
    mode: str, expected_exit: int, expected_output: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db_schema, "is_database_empty", lambda target_db: True)
    monkeypatch.setattr(
        db_schema,
        "download_latest_compatible_schema",
        lambda: (_ for _ in ()).throw(db_schema.SchemaRestoreUnavailable("no compatible artifact")),
    )

    result = runner.invoke(db_schema.db_restore_schema_if_fresh, [f"--mode={mode}"])

    assert result.exit_code == expected_exit
    assert expected_output in result.output


def test_restore_schema_fresh_recreates_target_db(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv("TARGET_DB", "posthog_e2e_test")
    monkeypatch.setattr(db_schema, "restore_schema_dump", lambda **kwargs: calls.append(kwargs))

    result = runner.invoke(db_schema.db_restore_schema_fresh)

    assert result.exit_code == 0
    assert calls == [{"target_db": "posthog_e2e_test", "recreate": True, "ensure_defaults": True}]
