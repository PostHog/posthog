import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest import mock

from posthog.clickhouse.client import sync_execute

from products.engineering_analytics.backend.facade.contracts import BROKEN_TEST_SPARKLINE_HOURS, BrokenTestState
from products.engineering_analytics.backend.logic.job_logs.constants import CI_LOGS_SERVICE_NAME
from products.engineering_analytics.backend.logic.queries import broken_tests as module
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.broken_tests import (
    _classify,
    _sparklines_by_fingerprint,
    query_broken_tests,
)
from products.engineering_analytics.backend.logic.sources import GitHubTables


# Ages are seconds-ago-from-now (smaller = more recent). last_master_hit_age is the fingerprint's most
# recent trunk failure; latest_completed_age is the matched job's newest completed run.
@pytest.mark.parametrize(
    "master_hits,age_hours,span_hours,branches,latest_conclusion,last_master_hit_age,latest_completed_age,expected",
    [
        # Breaking trunk: hit master and that job's latest run is still red — highest priority.
        (3, 5, 48, 5, "failure", 100, 50, BrokenTestState.BREAKING_MASTER),
        (1, 40, 100, 2, "timed_out", 100, 50, BrokenTestState.BREAKING_MASTER),
        # Breaking wins even when the row also looks novel (fresh + spreading).
        (3, 5, 5, 4, "failure", 100, 50, BrokenTestState.BREAKING_MASTER),
        # Novel burst: fresh (<24h), spread across >=3 branches, never on trunk.
        (0, 5, 5, 4, None, 0, None, BrokenTestState.NOVEL_BURST),
        # Hit trunk but the green run finished AFTER the last failure (100 < 1000) — a real recovery.
        (2, 40, 100, 3, "success", 1000, 100, BrokenTestState.POTENTIALLY_RESOLVED),
        # Green but STALE: the green predates the last trunk failure (1000 > 100), so the warehouse is
        # just lagging the fresher logs — not resolved, falls through to flaky.
        (2, 40, 100, 3, "success", 100, 1000, BrokenTestState.FLAKY),
        # Flaky: sporadic across >=2 branches over more than a day, not on trunk.
        (0, 100, 48, 3, None, 0, None, BrokenTestState.FLAKY),
        # Degradation: hit trunk but no job status (source unsynced) — falls through, not misreported.
        (3, 100, 48, 3, None, 100, None, BrokenTestState.FLAKY),
        # PR-only: one branch, recent, short span — the lowest signal.
        (0, 5, 2, 1, None, 0, None, BrokenTestState.PR_ONLY),
        # Not novel (only 2 branches) and not flaky (span within a day) → PR-only.
        (0, 5, 10, 2, None, 0, None, BrokenTestState.PR_ONLY),
    ],
)
def test_classify_states(
    master_hits, age_hours, span_hours, branches, latest_conclusion, last_master_hit_age, latest_completed_age, expected
):
    assert (
        _classify(
            master_hits=master_hits,
            age_hours=age_hours,
            span_hours=span_hours,
            branches=branches,
            latest_conclusion=latest_conclusion,
            last_master_hit_age=last_master_hit_age,
            latest_completed_age=latest_completed_age,
        )
        == expected
    )


def test_sparkline_fold_places_hours_oldest_first_and_skips_out_of_window():
    # hours_ago=0 is the newest slot (last), 23 the oldest (first); anything >=24 is dropped.
    rows = [
        ("fp", 0, 8),
        ("fp", 1, 6),
        ("fp", 23, 1),
        ("fp", 24, 99),  # out of window — must be ignored
        ("other", 0, 3),
    ]
    series = _sparklines_by_fingerprint(rows)

    assert len(series["fp"]) == BROKEN_TEST_SPARKLINE_HOURS
    assert series["fp"][BROKEN_TEST_SPARKLINE_HOURS - 1] == 8  # hours_ago 0 → last slot
    assert series["fp"][BROKEN_TEST_SPARKLINE_HOURS - 2] == 6  # hours_ago 1
    assert series["fp"][0] == 1  # hours_ago 23 → first slot
    assert sum(series["fp"]) == 15  # the 24-hours-ago bucket did not count
    assert "other" in series


def _fp_row(
    fingerprint,
    job_name,
    *,
    master_hits,
    branches,
    last_seen,
    workflow_name="wf",
    latest_run_id=1,
    age=100,
    span=48,
    last_master_hit_age=500,
):
    # Column order mirrors _FINGERPRINTS_SELECT (workflow_name + last_master_hit_age appended last).
    return (
        fingerprint,
        f"test_{fingerprint}",
        "AssertionError",
        job_name,
        datetime(2026, 7, 13, tzinfo=UTC),
        last_seen,
        age,
        span,
        10,
        branches,
        master_hits,
        "PostHog/posthog",
        latest_run_id,
        "some-branch",
        workflow_name,
        last_master_hit_age,
    )


def _run_query(*, fingerprint_rows, hourly_rows, master_rows, jobs_synced=True, limit=200):
    curated = mock.Mock()
    curated.repository = "PostHog/posthog"
    curated.jobs_source.return_value = "(jobs)" if jobs_synced else None

    def run_side_effect(_sql, *, query_type, **_kwargs):
        if "fingerprints" in query_type:
            return SimpleNamespace(results=fingerprint_rows)
        if "hourly" in query_type:
            return SimpleNamespace(results=hourly_rows)
        return SimpleNamespace(results=master_rows)

    curated.run.side_effect = run_side_effect
    return query_broken_tests(
        curated=curated,
        date_from=datetime(2026, 7, 13, tzinfo=UTC),
        hourly_from=datetime(2026, 7, 14, tzinfo=UTC),
        window_days=2,
        limit=limit,
    )


def test_query_joins_master_status_ranks_by_severity_and_attaches_trend():
    # A breaking-master row (its job is red) must outrank a flaky row regardless of recency, carry
    # its folded 24h trend, and the red job must surface in breaking_master_jobs. This is the whole
    # merge: fingerprints × job status → classified, ranked, sparkline-attached rows.
    result = _run_query(
        fingerprint_rows=[
            _fp_row("flaky-fp", "job-b", master_hits=0, branches=3, last_seen=datetime(2026, 7, 15, tzinfo=UTC)),
            _fp_row("break-fp", "job-a", master_hits=3, branches=4, last_seen=datetime(2026, 7, 14, tzinfo=UTC)),
        ],
        hourly_rows=[("break-fp", 0, 5), ("break-fp", 1, 2)],
        # (workflow_name, job_name, latest_conclusion, latest_completed_age)
        master_rows=[("wf", "job-a", "failure", 50), ("wf", "job-b", "success", 50)],
    )

    assert [row.fingerprint for row in result.rows] == ["break-fp", "flaky-fp"]
    assert result.rows[0].state == BrokenTestState.BREAKING_MASTER
    assert result.rows[1].state == BrokenTestState.FLAKY
    assert result.breaking_master_jobs == ["job-a"]
    # trend_24h is the fixed-width fold: newest hour last.
    assert result.rows[0].trend_24h[-1] == 5
    assert result.rows[0].trend_24h[-2] == 2
    # The flaky row had no hourly rows → all-zero trend of the contract width.
    assert result.rows[1].trend_24h == [0] * BROKEN_TEST_SPARKLINE_HOURS


def test_query_keys_master_status_by_workflow_not_just_job_name():
    # Two workflows reuse the job name "test": one is red on trunk, one green. Keying master status by
    # job name alone would let the green mask the red. Both fingerprints hit trunk, so the right verdicts
    # are breaking_master (red workflow) and potentially_resolved (green workflow, fresh green).
    result = _run_query(
        fingerprint_rows=[
            _fp_row(
                "red-wf-fp",
                "test",
                workflow_name="backend",
                master_hits=3,
                branches=3,
                last_seen=datetime(2026, 7, 15, tzinfo=UTC),
            ),
            _fp_row(
                "green-wf-fp",
                "test",
                workflow_name="frontend",
                master_hits=3,
                branches=3,
                last_seen=datetime(2026, 7, 15, tzinfo=UTC),
            ),
        ],
        hourly_rows=[],
        master_rows=[("backend", "test", "failure", 50), ("frontend", "test", "success", 50)],
    )

    by_fp = {row.fingerprint: row.state for row in result.rows}
    assert by_fp["red-wf-fp"] == BrokenTestState.BREAKING_MASTER
    assert by_fp["green-wf-fp"] == BrokenTestState.POTENTIALLY_RESOLVED


def test_query_degrades_without_job_source():
    # No jobs source → no master status query runs, breaking/resolved can't be decided, and a
    # trunk-hitting failure falls through to flaky rather than being called breaking_master.
    result = _run_query(
        fingerprint_rows=[
            _fp_row("fp", "job-a", master_hits=3, branches=3, last_seen=datetime(2026, 7, 15, tzinfo=UTC)),
        ],
        hourly_rows=[],
        master_rows=[],
        jobs_synced=False,
    )

    assert result.breaking_master_jobs == []
    assert result.rows[0].state == BrokenTestState.FLAKY


def test_query_truncates_by_limit():
    rows = [
        _fp_row(f"fp{i}", "job", master_hits=0, branches=3, last_seen=datetime(2026, 7, 15, tzinfo=UTC))
        for i in range(3)
    ]
    result = _run_query(fingerprint_rows=rows, hourly_rows=[], master_rows=[], limit=2)

    assert len(result.rows) == 2
    assert result.truncated is True


def test_query_returns_empty_without_repository_and_skips_reads():
    curated = mock.Mock()
    curated.repository = ""
    result = query_broken_tests(
        curated=curated,
        date_from=datetime(2026, 7, 13, tzinfo=UTC),
        hourly_from=datetime(2026, 7, 14, tzinfo=UTC),
        window_days=2,
        limit=200,
    )

    assert result.rows == []
    assert result.breaking_master_jobs == []
    # A team-global logs view with no source repository must not be scanned at all.
    curated.run.assert_not_called()


def test_build_query_embeds_the_failures_view():
    # Guards the private read path: the fingerprint scan reads the ci_failures builder as a subquery,
    # not the registered warehouse view by name (keeps the product off the global catalog).
    assert "engineering_analytics_ci_failures" not in module._FINGERPRINTS_SELECT
    assert "FAILED" in module.ci_failures.build_query()


class TestBrokenTestsQueryOverClickHouse(ClickhouseTestMixin, BaseTest):
    """The unit tests above mock curated.run, so the fingerprints/hourly SQL never actually runs.
    This drives query_broken_tests through real HogQL over seeded logs — the only place a SQL fault
    like an aggregate alias shadowing the WHERE-filtered `repo` column surfaces (it 500'd the endpoint
    in prod: "Aggregate function ... is found in WHERE")."""

    def _insert_logs(self, rows: list[dict[str, Any]]) -> None:
        payload = "".join(json.dumps({"team_id": self.team.id, **row}) + "\n" for row in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{payload}")

    def _failure_log(self, *, repo: str, test_id: str) -> dict[str, Any]:
        # attributes_map_str keys carry the "__str" suffix the logs table strips for the queryable map.
        return {
            "timestamp": "2026-07-10 12:00:00.000000",
            "body": f"FAILED {test_id} - AssertionError: boom",
            "service_name": CI_LOGS_SERVICE_NAME,
            "attributes_map_str": {
                "repo__str": repo,
                "branch__str": "master",
                "head_sha__str": "abc123",
                "workflow_name__str": "Backend CI",
                "job_name__str": "test (1)",
                "run_id__str": "100",
                "conclusion__str": "failure",
            },
        }

    def _source(self) -> CuratedGitHubSource:
        # workflow_jobs=None → jobs_source() is None → the master-status query is skipped, so this
        # exercises only the logs-backed fingerprints + hourly reads without warehouse setup.
        return CuratedGitHubSource(
            team=self.team,
            tables=GitHubTables(
                pull_requests="unused", workflow_runs="unused", workflow_jobs=None, repository="PostHog/posthog"
            ),
        )

    def test_fingerprints_query_runs_and_filters_by_repo(self) -> None:
        self._insert_logs(
            [
                self._failure_log(repo="PostHog/posthog", test_id="posthog/api/test_foo.py::test_bar"),
                self._failure_log(repo="other/repo", test_id="other/test_x.py::test_y"),
            ]
        )
        result = query_broken_tests(
            curated=self._source(),
            date_from=datetime(2026, 7, 9, tzinfo=UTC),
            hourly_from=datetime(2026, 7, 9, tzinfo=UTC),
            window_days=2,
            limit=200,
        )
        # No aggregate-in-WHERE 500, and lower(repo) binds to the column (not the any(repo) alias):
        # only the selected repo's failure comes back.
        assert [row.test_id for row in result.rows] == ["posthog/api/test_foo.py::test_bar"]
        assert result.rows[0].repo == "PostHog/posthog"
