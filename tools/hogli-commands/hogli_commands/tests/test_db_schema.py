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
    head_branch: str = db_schema.DEFAULT_BASE_BRANCH,
) -> db_schema.SchemaArtifact:
    return db_schema.SchemaArtifact(
        id=artifact_id,
        name=name,
        expired=expired,
        size_in_bytes=size_in_bytes,
        archive_download_url=f"https://api.github.com/artifacts/{artifact_id}/zip",
        head_sha=head_sha,
        head_branch=head_branch,
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


def test_select_newest_compatible_artifact_returns_most_recent() -> None:
    artifacts = [
        _artifact(1, "older", "2026-01-01T00:00:00Z"),
        _artifact(2, "newer", "2026-01-02T00:00:00Z"),
    ]

    assert db_schema.select_newest_compatible_artifact(artifacts) == artifacts[1]


@pytest.mark.parametrize(
    "artifact",
    [
        _artifact(1, "sha", "2026-01-01T00:00:00Z", expired=True),
        _artifact(1, "sha", "2026-01-01T00:00:00Z", size_in_bytes=100),
        _artifact(1, "", "2026-01-01T00:00:00Z"),
        _artifact(1, "sha", "2026-01-01T00:00:00Z", name="other"),
        _artifact(1, "sha", "2026-01-01T00:00:00Z", head_branch="some-pr-branch"),
    ],
)
def test_select_ignores_invalid_artifacts(artifact: db_schema.SchemaArtifact) -> None:
    assert db_schema.select_newest_compatible_artifact([artifact]) is None


def test_select_honors_custom_base_branch() -> None:
    master_artifact = _artifact(1, "sha-a", "2026-01-01T00:00:00Z", head_branch="master")
    release_artifact = _artifact(2, "sha-b", "2026-01-02T00:00:00Z", head_branch="release-26.1")

    selected = db_schema.select_newest_compatible_artifact(
        [master_artifact, release_artifact],
        base_branch="release-26.1",
    )

    assert selected == release_artifact


def test_download_diagnostics_on_no_compatible_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    artifacts = [
        _artifact(10, "pr-sha", "2026-01-01T00:00:00Z", head_branch="some-pr"),
        _artifact(11, "master-sha", "2026-01-02T00:00:00Z", head_branch="some-other-pr"),
    ]
    monkeypatch.setattr(db_schema, "_github_token", lambda: "token")
    monkeypatch.setattr(db_schema, "fetch_schema_artifacts", lambda **kwargs: artifacts)

    split_runner = CliRunner(mix_stderr=False)
    result = split_runner.invoke(db_schema.db_download_schema, [])

    assert result.exit_code != 0
    assert "Fetched 2 migrated-schema artifact(s)" in result.stderr
    assert "After name/expiry/size/branch filters: 0 candidate(s)" in result.stderr


def test_effective_base_branch_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTHOG_SCHEMA_RESTORE_BASE_BRANCH", "release-26.1")
    assert db_schema._effective_base_branch(None) == "release-26.1"
    assert db_schema._effective_base_branch("override") == "override"

    monkeypatch.delenv("POSTHOG_SCHEMA_RESTORE_BASE_BRANCH", raising=False)
    assert db_schema._effective_base_branch(None) == db_schema.DEFAULT_BASE_BRANCH


@pytest.mark.parametrize(
    "mode,is_empty,expected_inspections",
    [
        ("off", True, []),
        ("auto", False, ["posthog"]),
    ],
)
def test_restore_schema_if_fresh_skips_without_download(
    mode: db_schema.ArtifactMode,
    is_empty: bool,
    expected_inspections: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspections: list[str] = []

    def fake_is_database_empty(target_db: str) -> bool:
        inspections.append(target_db)
        return is_empty

    monkeypatch.setattr(db_schema, "is_database_empty", fake_is_database_empty)
    monkeypatch.setattr(
        db_schema,
        "download_latest_compatible_schema",
        lambda **kwargs: pytest.fail("download should not run"),
    )

    assert db_schema.restore_schema_if_fresh(target_db="posthog", mode=mode) is False
    assert inspections == expected_inspections


def test_restore_schema_if_fresh_recreates_empty_db(monkeypatch: pytest.MonkeyPatch) -> None:
    restore_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(db_schema, "is_database_empty", lambda target_db: True)
    monkeypatch.setattr(db_schema, "download_latest_compatible_schema", lambda **kwargs: None)
    monkeypatch.setattr(db_schema, "restore_schema_dump", lambda **kwargs: restore_calls.append(kwargs))

    assert db_schema.restore_schema_if_fresh(target_db="posthog", mode="auto") is True
    assert restore_calls == [{"target_db": "posthog", "recreate": True, "ensure_defaults": True}]


def test_restore_schema_if_fresh_skips_when_db_populated_after_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If another process writes to the DB during the artifact download, the
    post-download re-check must abort before DROP/CREATE."""
    empty_responses = iter([True, False])
    monkeypatch.setattr(db_schema, "is_database_empty", lambda target_db: next(empty_responses))
    monkeypatch.setattr(db_schema, "download_latest_compatible_schema", lambda **kwargs: None)
    monkeypatch.setattr(
        db_schema,
        "restore_schema_dump",
        lambda **kwargs: pytest.fail("restore must not run when DB stopped being empty"),
    )

    assert db_schema.restore_schema_if_fresh(target_db="posthog", mode="auto") is False


def test_run_psql_with_gzip_input_uses_transactional_error_stopping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_path = tmp_path / "schema.sql.gz"
    _write_schema(schema_path)
    commands: list[list[str]] = []

    class FakeStdin:
        def __init__(self) -> None:
            self.data = b""

        def write(self, chunk: bytes) -> int:
            self.data += chunk
            return len(chunk)

        def close(self) -> None:
            pass

    class SuccessfulProcess:
        def __init__(self) -> None:
            self.stdin = FakeStdin()

        def wait(self) -> int:
            return 0

        def kill(self) -> None:
            pytest.fail("process should not be killed")

    def fake_popen(command: list[str], **kwargs: object) -> SuccessfulProcess:
        commands.append(command)
        return SuccessfulProcess()

    monkeypatch.setattr(db_schema.subprocess, "Popen", fake_popen)

    db_schema._run_psql_with_gzip_input(schema_path, "posthog")

    assert len(commands) == 1
    assert "-v" in commands[0]
    assert "ON_ERROR_STOP=1" in commands[0]
    assert "--single-transaction" in commands[0]


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


def test_restore_schema_dump_recreate_cleans_up_after_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema_path = tmp_path / "schema.sql.gz"
    _write_schema(schema_path)
    commands: list[list[str]] = []

    monkeypatch.setattr(db_schema, "_run", lambda command, env=None: commands.append(command))
    monkeypatch.setattr(
        db_schema,
        "_run_psql_with_gzip_input",
        lambda gzip_path, target_db: (_ for _ in ()).throw(db_schema.SchemaRestoreError("restore failed")),
    )
    monkeypatch.setattr(
        db_schema,
        "_ensure_migration_defaults",
        lambda target_db: pytest.fail("defaults should not run after restore failure"),
    )

    with pytest.raises(db_schema.SchemaRestoreError, match="restore failed"):
        db_schema.restore_schema_dump(target_db="test_posthog", recreate=True, schema_path=schema_path)

    admin_sql = [command[-1] for command in commands]
    terminate_sql = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = 'test_posthog' AND pid <> pg_backend_pid();"
    )
    assert admin_sql == [
        terminate_sql,
        "DROP DATABASE IF EXISTS test_posthog;",
        "CREATE DATABASE test_posthog;",
        terminate_sql,
        "DROP DATABASE IF EXISTS test_posthog;",
        "CREATE DATABASE test_posthog;",
    ]


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
        lambda **kwargs: (_ for _ in ()).throw(db_schema.SchemaRestoreUnavailable("no compatible artifact")),
    )

    result = runner.invoke(db_schema.db_restore_schema_if_fresh, [f"--mode={mode}"])

    assert result.exit_code == expected_exit
    assert expected_output in result.output


def test_restore_schema_if_fresh_auto_does_not_fallback_when_cleanup_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        db_schema,
        "restore_schema_if_fresh",
        lambda **kwargs: (_ for _ in ()).throw(db_schema.SchemaRestoreCleanupFailed("cleanup failed")),
    )

    result = runner.invoke(db_schema.db_restore_schema_if_fresh, ["--mode=auto"])

    assert result.exit_code == 1
    assert "cleanup failed" in result.output


def test_restore_schema_fresh_recreates_target_db(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv("TARGET_DB", "posthog_e2e_test")
    monkeypatch.setattr(db_schema, "restore_schema_dump", lambda **kwargs: calls.append(kwargs))

    result = runner.invoke(db_schema.db_restore_schema_fresh)

    assert result.exit_code == 0
    assert calls == [{"target_db": "posthog_e2e_test", "recreate": True, "ensure_defaults": True}]


@pytest.mark.parametrize(
    "command",
    [
        db_schema.db_download_schema,
        db_schema.db_restore_test_db,
        db_schema.db_restore_schema_fresh,
        db_schema.db_restore_schema_if_fresh,
    ],
    ids=lambda cmd: cmd.name,
)
def test_converted_commands_accept_forwarded_yes_flag(command: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """hogli composite commands forward --yes to children; converted click
    commands must silently accept it (regression for db:prime-test-db --yes)."""
    monkeypatch.setattr(db_schema, "download_latest_compatible_schema", lambda **kwargs: None)
    monkeypatch.setattr(db_schema, "restore_schema_dump", lambda **kwargs: None)
    monkeypatch.setattr(db_schema, "restore_schema_if_fresh", lambda **kwargs: None)

    for flag in ("--yes", "-y"):
        result = runner.invoke(command, [flag])
        assert result.exit_code == 0, f"{command.name} {flag} failed: {result.output}"
