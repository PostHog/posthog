from __future__ import annotations

from collections.abc import Sequence

import pytest

import click
import hogli_commands.migrations as migrations
from click.testing import CliRunner


def _label(info: migrations.MigrationInfo) -> str:
    return f"{info.app}.{info.name}"


def _info(label: str) -> migrations.MigrationInfo:
    app, name = label.split(".")
    return migrations.MigrationInfo(app=app, name=name)


# Stands in for every boundary the migration commands can change state through.
class Harness:
    def __init__(self) -> None:
        self.orphaned: list[migrations.MigrationInfo] = []
        self.pending: list[migrations.MigrationInfo] = []
        self.cached: set[str] = set()
        # Uncached orphans that the git search can recover into the cache
        self.git_recovered: set[str] = set()
        self.rollback_failures: set[str] = set()
        self.apply_results: list[migrations.MigrationResult] = []
        # What the command asked the boundaries to do, with the dry-run flag it passed
        self.rollbacks: list[tuple[str, bool]] = []
        self.removals: list[tuple[list[str], bool]] = []
        self.applies: list[tuple[list[str], bool]] = []

    def set_state(self, orphaned: Sequence[str] = (), pending: Sequence[str] = ()) -> None:
        self.orphaned = [_info(label) for label in orphaned]
        self.pending = [_info(label) for label in pending]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    h = Harness()

    def rollback(app: str, name: str, dry_run: bool = False) -> bool:
        h.rollbacks.append((f"{app}.{name}", dry_run))
        return f"{app}.{name}" not in h.rollback_failures

    def remove(orphaned: list[migrations.MigrationInfo], dry_run: bool = False) -> bool:
        h.removals.append(([_label(m) for m in orphaned], dry_run))
        return True

    def apply(
        pending: list[migrations.MigrationInfo] | None = None, dry_run: bool = False
    ) -> migrations.MigrationResult:
        h.applies.append(([_label(m) for m in pending or []], dry_run))
        if h.apply_results:
            return h.apply_results.pop(0)
        return migrations.MigrationResult(success=True)

    monkeypatch.setattr(
        migrations,
        "_compute_migration_diff",
        lambda: migrations.MigrationDiff(orphaned=list(h.orphaned), pending=list(h.pending)),
    )
    monkeypatch.setattr(migrations, "_get_cached_migration", lambda app, name: f"{app}.{name}" in h.cached)
    monkeypatch.setattr(migrations, "_rollback_migration_with_cache", rollback)
    monkeypatch.setattr(migrations, "_remove_orphaned_migrations", remove)
    monkeypatch.setattr(migrations, "_apply_migrations", apply)

    def fetch_from_git(uncached: list[migrations.MigrationInfo]) -> migrations.GitRecoveryResult:
        return migrations.GitRecoveryResult(
            newly_cached=[m for m in uncached if _label(m) in h.git_recovered],
            still_uncached=[m for m in uncached if _label(m) not in h.git_recovered],
        )

    monkeypatch.setattr(migrations, "_fetch_uncached_from_git", fetch_from_git)
    monkeypatch.setattr(migrations, "_find_migration_branch", lambda app, name: None)
    monkeypatch.setattr(migrations, "_fake_migration", lambda app, name: True)
    monkeypatch.setattr(migrations, "get_managed_app_paths", lambda root: {})
    # Nothing in these tests may reach Postgres
    monkeypatch.setattr(migrations, "_get_migrations_in_db", lambda: {})
    return h


@pytest.mark.parametrize(
    "command,args",
    [
        (migrations.migrations_down, ["--dry-run"]),
        (migrations.migrations_sync, ["--dry-run"]),
        (migrations.migrations_up, ["--dry-run"]),
    ],
)
def test_dry_run_only_plans(harness: Harness, command: click.Command, args: list[str]) -> None:
    harness.set_state(orphaned=["posthog.0002_orphan"], pending=["posthog.0003_new"])
    harness.cached = {"posthog.0002_orphan"}

    result = CliRunner().invoke(command, args)

    assert result.exit_code == 0
    assert all(dry_run for _, dry_run in harness.rollbacks)
    assert all(dry_run for _, dry_run in harness.applies)
    assert harness.removals == []


@pytest.mark.parametrize(
    "command,args",
    [
        (migrations.migrations_down, []),
        (migrations.migrations_sync, []),
    ],
)
def test_declining_the_prompt_changes_nothing(harness: Harness, command: click.Command, args: list[str]) -> None:
    harness.set_state(orphaned=["posthog.0002_orphan"], pending=["posthog.0003_new"])
    harness.cached = {"posthog.0002_orphan"}

    result = CliRunner().invoke(command, args, input="n\n")

    assert result.exit_code == 1
    assert "Aborted." in result.output
    assert harness.rollbacks == []
    assert harness.applies == []


def test_uncached_orphan_without_force_stops_before_any_change(harness: Harness) -> None:
    harness.set_state(orphaned=["posthog.0002_orphan"])

    result = CliRunner().invoke(migrations.migrations_sync, ["--yes"])

    assert result.exit_code == 1
    assert "cannot be auto-rolled back" in result.output
    assert harness.rollbacks == []
    assert harness.removals == []


def test_force_removes_records_for_uncached_orphans_only(harness: Harness) -> None:
    harness.set_state(orphaned=["posthog.0002_orphan", "posthog.0004_gone"])
    harness.cached = {"posthog.0002_orphan"}

    result = CliRunner().invoke(migrations.migrations_down, ["--force", "--yes"])

    assert result.exit_code == 0
    assert harness.rollbacks == [("posthog.0002_orphan", False)]
    assert harness.removals == [(["posthog.0004_gone"], False)]


def test_force_dry_run_plans_the_record_removal_without_doing_it(harness: Harness) -> None:
    harness.set_state(orphaned=["posthog.0004_gone"])

    result = CliRunner().invoke(migrations.migrations_down, ["--force", "--dry-run"])

    assert result.exit_code == 0
    assert harness.removals == [(["posthog.0004_gone"], True)]
    assert harness.rollbacks == []


def test_git_recovered_orphan_is_rolled_back_not_record_deleted(harness: Harness) -> None:
    harness.set_state(orphaned=["posthog.0002_orphan", "posthog.0004_gone"])
    harness.cached = {"posthog.0002_orphan"}
    harness.git_recovered = {"posthog.0004_gone"}

    result = CliRunner().invoke(migrations.migrations_down, ["--yes"])

    assert result.exit_code == 0
    assert harness.rollbacks == [("posthog.0002_orphan", False), ("posthog.0004_gone", False)]
    assert harness.removals == []


def test_failed_rollback_stops_before_applying_pending(harness: Harness) -> None:
    harness.set_state(orphaned=["posthog.0002_orphan"], pending=["posthog.0003_new"])
    harness.cached = {"posthog.0002_orphan"}
    harness.rollback_failures = {"posthog.0002_orphan"}

    result = CliRunner().invoke(migrations.migrations_sync, ["--yes"])

    assert result.exit_code == 1
    assert "Failed to roll back posthog.0002_orphan" in result.output
    assert harness.applies == []


@pytest.mark.parametrize(
    "command,args",
    [
        (migrations.migrations_up, ["--yes"]),
        (migrations.migrations_sync, ["--yes"]),
    ],
)
def test_duplicate_schema_is_faked_then_dropped_from_the_retry(
    harness: Harness, command: click.Command, args: list[str]
) -> None:
    harness.set_state(pending=["posthog.0003_new", "posthog.0005_later"])
    harness.apply_results = [
        migrations.MigrationResult(
            success=False,
            error_type="duplicate_column",
            error_message='column "foo" of relation "posthog_team" already exists',
            failed_migration=("posthog", "0003_new"),
        )
    ]

    result = CliRunner().invoke(command, args)

    assert result.exit_code == 0
    assert [pending for pending, _ in harness.applies] == [
        ["posthog.0003_new", "posthog.0005_later"],
        ["posthog.0005_later"],
    ]


@pytest.mark.parametrize(
    "command,args",
    [
        (migrations.migrations_up, ["--yes"]),
        (migrations.migrations_sync, ["--yes"]),
    ],
)
def test_unrecoverable_apply_error_reports_and_exits(harness: Harness, command: click.Command, args: list[str]) -> None:
    harness.set_state(pending=["posthog.0003_new"])
    harness.apply_results = [
        migrations.MigrationResult(success=False, error_type="other", error_message="relation does not exist")
    ]

    result = CliRunner().invoke(command, args)

    assert result.exit_code == 1
    assert "Failed to apply migrations" in result.output
    assert "relation does not exist" in result.output
