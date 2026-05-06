"""Tests for migration_risk.py — check-run interpretation."""

import json

import pytest

from migration_risk import migration_check_pending, safe_migration_files


def _check(
    name: str = "Migration risk",
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    completed_at: str = "2026-04-30T12:00:00Z",
    analyzed_paths: list[str] | None = None,
    summary_override: str | None = None,
) -> dict:
    """Build a fake check_run.

    `analyzed_paths` becomes the JSON inside the `<!-- stamphog:v1 [...] -->`
    marker; pass `None` to omit the marker entirely (simulates older checks
    or non-success conclusions). `summary_override` lets tests inject raw
    summary text (e.g. malformed markers).
    """
    if summary_override is not None:
        summary = summary_override
    elif analyzed_paths is None:
        summary = "no marker here"
    else:
        summary = f"<!-- stamphog:v1 {json.dumps(analyzed_paths)} -->\nreport body"
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "completed_at": completed_at,
        "output": {"summary": summary},
    }


# ── safe_migration_files ─────────────────────────────────────────


def test_success_check_pairs_each_migration_with_its_max_migration_txt() -> None:
    """Happy path. Every analyzed migration in the marker that's also in the PR
    diff gets its directory's max_migration.txt paired automatically, across
    multiple migration roots; non-migration paths are ignored."""
    files = [
        "posthog/migrations/1125_x.py",
        "products/signals/backend/migrations/0042_y.py",
        "posthog/api/some.py",
    ]
    check = _check(
        analyzed_paths=[
            "posthog/migrations/1125_x.py",
            "products/signals/backend/migrations/0042_y.py",
        ]
    )

    assert safe_migration_files([check], files) == {
        "posthog/migrations/1125_x.py",
        "posthog/migrations/max_migration.txt",
        "products/signals/backend/migrations/0042_y.py",
        "products/signals/backend/migrations/max_migration.txt",
    }


def test_bypass_scoped_to_intersection_of_marker_and_pr() -> None:
    """The marker is the source of truth. A path the analyzer never classified
    (e.g. ClickHouse migration in the same PR) must not be bypassed even when
    the Django side concluded success."""
    files = [
        "posthog/migrations/1125_x.py",
        "posthog/clickhouse/migrations/0099_unrelated.py",
    ]
    # Marker only lists the Django one — the analyzer doesn't touch ClickHouse.
    check = _check(analyzed_paths=["posthog/migrations/1125_x.py"])

    assert safe_migration_files([check], files) == {
        "posthog/migrations/1125_x.py",
        "posthog/migrations/max_migration.txt",
    }


def test_max_migration_txt_paired_only_for_analyzed_dirs() -> None:
    """Sibling pairing must follow the analyzer's scope — a ClickHouse
    `max_migration.txt` should never be added just because some other dir
    contributed a Safe migration."""
    files = [
        "posthog/migrations/1125_x.py",
        "posthog/clickhouse/migrations/0099_x.py",
    ]
    check = _check(analyzed_paths=["posthog/migrations/1125_x.py"])

    safe = safe_migration_files([check], files)

    assert "posthog/clickhouse/migrations/max_migration.txt" not in safe
    assert "posthog/migrations/max_migration.txt" in safe


def test_empty_marker_means_no_bypass() -> None:
    """Zero Django migrations to analyze still publishes success, but with an
    empty marker — bypass set is empty and the deny-list applies normally."""
    files = ["posthog/clickhouse/migrations/0099_x.py"]
    check = _check(analyzed_paths=[])

    assert safe_migration_files([check], files) == set()


@pytest.mark.parametrize(
    "summary",
    [
        pytest.param("no marker here at all", id="no-marker"),
        pytest.param("<!-- stamphog:v1 not-json-array -->", id="malformed-json"),
        pytest.param('<!-- stamphog:v1 ["missing close ', id="truncated"),
        pytest.param('<!-- stamphog:v1 {"shape":"wrong"} -->', id="wrong-shape"),
    ],
)
def test_malformed_or_missing_marker_falls_back_to_no_bypass(summary: str) -> None:
    """Any failure to parse the marker is treated as "no analyzer signal,"
    which is the safe default — deny-list applies normally."""
    check = _check(summary_override=summary)
    assert safe_migration_files([check], ["posthog/migrations/1125_x.py"]) == set()


@pytest.mark.parametrize(
    "check_runs",
    [
        pytest.param([], id="no-checks"),
        pytest.param([_check(name="other-ci")], id="different-check-name"),
        pytest.param(
            [_check(conclusion="failure", analyzed_paths=["posthog/migrations/1125_x.py"])], id="completed-failure"
        ),
        pytest.param(
            [_check(conclusion="neutral", analyzed_paths=["posthog/migrations/1125_x.py"])], id="completed-needs-review"
        ),
        pytest.param([_check(status="in_progress", conclusion=None)], id="in-flight"),
    ],
)
def test_no_bypass_unless_check_completed_with_success(check_runs: list[dict]) -> None:
    """Bypass requires an explicit `success` conclusion on a completed
    `Migration risk` check; everything else falls back to the deny-list,
    even when the marker would otherwise list the file."""
    assert safe_migration_files(check_runs, ["posthog/migrations/1125_x.py"]) == set()


def test_latest_completed_run_wins_over_older_and_in_flight() -> None:
    """CI re-runs leave duplicate checks. The most recent completed run wins,
    even when a newer in-flight run is present (it has no completed_at)."""
    older_failure = _check(
        conclusion="failure",
        completed_at="2026-04-30T10:00:00Z",
        analyzed_paths=["posthog/migrations/1125_x.py"],
    )
    newer_success = _check(
        conclusion="success",
        completed_at="2026-04-30T12:00:00Z",
        analyzed_paths=["posthog/migrations/1125_x.py"],
    )
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
    assert (
        migration_check_pending(
            [_check(conclusion=conclusion, analyzed_paths=["posthog/migrations/1125_x.py"])],
            ["posthog/migrations/1125_x.py"],
        )
        is False
    )


def test_not_pending_when_pr_has_no_real_migrations() -> None:
    """No migration files means there's nothing to wait for, regardless of
    what other checks are in flight on the same head SHA."""
    assert migration_check_pending([_check(status="in_progress", conclusion=None)], ["posthog/api/views.py"]) is False
