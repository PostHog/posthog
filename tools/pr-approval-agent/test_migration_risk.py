"""Tests for migration_risk.py — check-run interpretation."""

import pytest

from migration_risk import migration_check_pending, safe_migration_files


def _check(
    name: str = "Migration risk",
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    completed_at: str = "2026-04-30T12:00:00Z",
) -> dict:
    return {"name": name, "status": status, "conclusion": conclusion, "completed_at": completed_at}


# ── safe_migration_files ─────────────────────────────────────────


def test_success_check_pairs_each_migration_with_its_max_migration_txt() -> None:
    """Happy path. Every migration file gets its directory's max_migration.txt
    paired automatically, across multiple migration roots; non-migration paths
    are ignored."""
    files = [
        "posthog/migrations/1125_x.py",
        "products/signals/backend/migrations/0042_y.py",
        "posthog/api/some.py",
    ]

    assert safe_migration_files([_check()], files) == {
        "posthog/migrations/1125_x.py",
        "posthog/migrations/max_migration.txt",
        "products/signals/backend/migrations/0042_y.py",
        "products/signals/backend/migrations/max_migration.txt",
    }


def test_only_real_migration_files_count() -> None:
    """`__init__.py` and files outside a `migrations/` dir are excluded —
    the same `_is_migration_file` filter is reused by `migration_check_pending`."""
    files = [
        "posthog/migrations/__init__.py",
        "posthog/migrations/1125_real.py",
        "posthog/api/whatever.py",
    ]

    assert safe_migration_files([_check()], files) == {
        "posthog/migrations/1125_real.py",
        "posthog/migrations/max_migration.txt",
    }


@pytest.mark.parametrize(
    "check_runs",
    [
        pytest.param([], id="no-checks"),
        pytest.param([_check(name="other-ci")], id="different-check-name"),
        pytest.param([_check(conclusion="failure")], id="completed-failure"),
        pytest.param([_check(conclusion="neutral")], id="completed-needs-review"),
        pytest.param([_check(status="in_progress", conclusion=None)], id="in-flight"),
    ],
)
def test_no_bypass_unless_check_completed_with_success(check_runs: list[dict]) -> None:
    """Bypass requires an explicit `success` conclusion on a completed
    `Migration risk` check; everything else falls back to the deny-list."""
    assert safe_migration_files(check_runs, ["posthog/migrations/1125_x.py"]) == set()


def test_latest_completed_run_wins_over_older_and_in_flight() -> None:
    """CI re-runs leave duplicate checks. The most recent completed run wins,
    even when a newer in-flight run is present (it has no completed_at)."""
    older_failure = _check(conclusion="failure", completed_at="2026-04-30T10:00:00Z")
    newer_success = _check(conclusion="success", completed_at="2026-04-30T12:00:00Z")
    in_flight = _check(status="in_progress", conclusion=None, completed_at="")

    assert safe_migration_files([older_failure, newer_success, in_flight], ["posthog/migrations/1125_x.py"]) == {
        "posthog/migrations/1125_x.py",
        "posthog/migrations/max_migration.txt",
    }


# ── migration_check_pending ──────────────────────────────────────


@pytest.mark.parametrize(
    "check_runs",
    [
        pytest.param([], id="no-check"),
        pytest.param([_check(status="in_progress", conclusion=None)], id="in-progress"),
        pytest.param([_check(status="queued", conclusion=None)], id="queued"),
    ],
)
def test_pending_when_pr_has_migrations_and_no_completed_check(check_runs: list[dict]) -> None:
    """Drives the deny-with-retry message: anything short of a completed check
    means the verdict isn't in yet."""
    assert migration_check_pending(check_runs, ["posthog/migrations/1125_x.py"]) is True


@pytest.mark.parametrize("conclusion", ["success", "failure"])
def test_not_pending_once_check_has_completed(conclusion: str) -> None:
    """Verdict is in even when not success — caller chooses how to act on it."""
    assert migration_check_pending([_check(conclusion=conclusion)], ["posthog/migrations/1125_x.py"]) is False


def test_not_pending_when_pr_has_no_real_migrations() -> None:
    """No migration files means there's nothing to wait for, regardless of
    what other checks are in flight on the same head SHA."""
    assert migration_check_pending([_check(status="in_progress", conclusion=None)], ["posthog/api/views.py"]) is False
