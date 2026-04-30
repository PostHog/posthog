"""Tests for migration_risk.py — check-run interpretation."""

import pytest

from migration_risk import is_waiting_for_migration_check, migration_check_pending, safe_migration_files


def _check(
    name: str = "Migration risk",
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    completed_at: str = "2026-04-30T12:00:00Z",
) -> dict:
    return {"name": name, "status": status, "conclusion": conclusion, "completed_at": completed_at}


# ── Happy path ───────────────────────────────────────────────────


def test_success_check_marks_migrations_as_safe() -> None:
    files = ["posthog/migrations/1125_x.py", "posthog/api/some.py"]

    result = safe_migration_files([_check()], files)

    assert result == {"posthog/migrations/1125_x.py", "posthog/migrations/max_migration.txt"}


def test_pairs_max_migration_for_each_distinct_dir() -> None:
    files = [
        "posthog/migrations/1125_x.py",
        "products/signals/backend/migrations/0042_y.py",
    ]

    assert safe_migration_files([_check()], files) == {
        "posthog/migrations/1125_x.py",
        "posthog/migrations/max_migration.txt",
        "products/signals/backend/migrations/0042_y.py",
        "products/signals/backend/migrations/max_migration.txt",
    }


def test_ignores_init_and_non_migration_paths() -> None:
    files = [
        "posthog/migrations/__init__.py",
        "posthog/migrations/1125_real.py",
        "posthog/api/whatever.py",
        "frontend/src/index.tsx",
    ]

    assert safe_migration_files([_check()], files) == {
        "posthog/migrations/1125_real.py",
        "posthog/migrations/max_migration.txt",
    }


# ── Non-success conclusions and fall-back behavior ───────────────


@pytest.mark.parametrize("conclusion", ["neutral", "failure", "cancelled", "timed_out", "action_required", None])
def test_non_success_conclusion_falls_back_to_deny_list(conclusion) -> None:
    """Anything other than `success` means deny-list applies — empty result."""
    result = safe_migration_files(
        [_check(conclusion=conclusion)],
        ["posthog/migrations/1125_x.py"],
    )

    assert result == set()


@pytest.mark.parametrize("status", ["queued", "in_progress"])
def test_in_flight_check_falls_back_to_deny_list(status: str) -> None:
    """The race-condition guard: if CI hasn't completed, we don't trust it."""
    result = safe_migration_files(
        [_check(status=status, conclusion=None)],
        ["posthog/migrations/1125_x.py"],
    )

    assert result == set()


def test_no_migration_check_falls_back() -> None:
    """No `Migration risk` check on the head commit → deny-list applies."""
    result = safe_migration_files([_check(name="other-ci")], ["posthog/migrations/1125_x.py"])

    assert result == set()


def test_empty_check_runs_falls_back() -> None:
    assert safe_migration_files([], ["posthog/migrations/1125_x.py"]) == set()


# ── Multi-check tiebreaking (re-runs leave duplicates) ───────────


def test_picks_latest_completed_when_multiple_runs_exist() -> None:
    """CI re-runs can leave multiple `Migration risk` checks on one commit.
    The most recent completed run wins."""
    older_failure = _check(conclusion="failure", completed_at="2026-04-30T10:00:00Z")
    newer_success = _check(conclusion="success", completed_at="2026-04-30T12:00:00Z")

    result = safe_migration_files([older_failure, newer_success], ["posthog/migrations/1125_x.py"])

    assert result == {"posthog/migrations/1125_x.py", "posthog/migrations/max_migration.txt"}


def test_picks_latest_even_when_newer_is_failure() -> None:
    older_success = _check(conclusion="success", completed_at="2026-04-30T10:00:00Z")
    newer_failure = _check(conclusion="failure", completed_at="2026-04-30T12:00:00Z")

    assert safe_migration_files([older_success, newer_failure], ["posthog/migrations/1125_x.py"]) == set()


def test_in_flight_run_doesnt_shadow_completed_run() -> None:
    """If CI has a re-run in flight while an earlier successful run exists,
    we still trust the completed result for the current head SHA.
    (Both are bound to the same head_sha by GitHub's API, so this is fine.)"""
    completed_success = _check(conclusion="success", completed_at="2026-04-30T10:00:00Z")
    in_flight = _check(status="in_progress", conclusion=None, completed_at="")

    result = safe_migration_files([completed_success, in_flight], ["posthog/migrations/1125_x.py"])

    assert result == {"posthog/migrations/1125_x.py", "posthog/migrations/max_migration.txt"}


# ── migration_check_pending: signals the "WAITING" state ─────────


def test_pending_when_check_missing_and_pr_has_migrations() -> None:
    assert migration_check_pending([], ["posthog/migrations/1125_x.py"]) is True


def test_pending_when_check_in_progress() -> None:
    assert (
        migration_check_pending(
            [_check(status="in_progress", conclusion=None, completed_at="")],
            ["posthog/migrations/1125_x.py"],
        )
        is True
    )


def test_pending_when_check_queued() -> None:
    assert (
        migration_check_pending(
            [_check(status="queued", conclusion=None, completed_at="")],
            ["posthog/migrations/1125_x.py"],
        )
        is True
    )


@pytest.mark.parametrize("conclusion", ["success", "neutral", "failure", "cancelled", "timed_out"])
def test_not_pending_when_check_completed(conclusion: str) -> None:
    """Once the check has reached `completed`, the verdict is in — not pending."""
    assert (
        migration_check_pending(
            [_check(conclusion=conclusion)],
            ["posthog/migrations/1125_x.py"],
        )
        is False
    )


def test_not_pending_when_pr_has_no_migrations() -> None:
    """No migration files means there's nothing to wait for."""
    assert migration_check_pending([], ["posthog/api/views.py"]) is False
    assert (
        migration_check_pending(
            [_check(status="in_progress", conclusion=None)],
            ["posthog/api/views.py"],
        )
        is False
    )


def test_not_pending_when_only_init_migrations() -> None:
    """__init__.py inside migrations/ shouldn't count as a real migration."""
    assert migration_check_pending([], ["posthog/migrations/__init__.py"]) is False


# ── is_waiting_for_migration_check: gate-level WAITING decision ──


def test_waiting_when_only_migrations_deny_and_check_pending() -> None:
    assert (
        is_waiting_for_migration_check(
            deny_categories=["migrations"],
            non_deny_gate_failures=[],
            check_runs=[],
            pr_file_paths=["posthog/migrations/1125_x.py"],
        )
        is True
    )


def test_not_waiting_when_other_deny_categories_present() -> None:
    """If auth or other categories also deny, the analyzer finishing won't unblock."""
    assert (
        is_waiting_for_migration_check(
            deny_categories=["migrations", "auth"],
            non_deny_gate_failures=[],
            check_runs=[],
            pr_file_paths=["posthog/migrations/1125_x.py", "posthog/api/auth.py"],
        )
        is False
    )


def test_not_waiting_when_no_deny_at_all() -> None:
    """No deny means we don't need to wait — gates pass already."""
    assert (
        is_waiting_for_migration_check(
            deny_categories=[],
            non_deny_gate_failures=[],
            check_runs=[],
            pr_file_paths=["posthog/migrations/1125_x.py"],
        )
        is False
    )


def test_not_waiting_when_size_or_prereq_gate_fails() -> None:
    """Other failing gates (size, prerequisites) don't clear when analyzer finishes."""
    assert (
        is_waiting_for_migration_check(
            deny_categories=["migrations"],
            non_deny_gate_failures=["size"],
            check_runs=[],
            pr_file_paths=["posthog/migrations/1125_x.py"],
        )
        is False
    )


def test_not_waiting_when_check_already_completed() -> None:
    assert (
        is_waiting_for_migration_check(
            deny_categories=["migrations"],
            non_deny_gate_failures=[],
            check_runs=[_check(conclusion="failure")],
            pr_file_paths=["posthog/migrations/1125_x.py"],
        )
        is False
    )
