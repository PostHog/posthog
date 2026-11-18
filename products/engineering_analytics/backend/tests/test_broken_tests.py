import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest import mock

from parameterized import parameterized

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


# Ages are seconds before now, so a smaller age is more recent. last_master_hit_age is the newest trunk
# failure of the fingerprint, and latest_completed_age is the newest completed run of the matched job.
@pytest.mark.parametrize(
    "master_hits,queue_hits,pr_hits,age_hours,span_hours,branches,latest_conclusion,last_master_hit_age,latest_completed_age,expected",
    [
        (3, 0, 5, 5, 48, 5, "failure", 100, 50, BrokenTestState.BREAKING_MASTER),
        (1, 0, 2, 40, 100, 2, "timed_out", 100, 50, BrokenTestState.BREAKING_MASTER),
        # This row also looks novel, because it is fresh and spreading.
        (3, 0, 4, 5, 5, 4, "failure", 100, 50, BrokenTestState.BREAKING_MASTER),
        # This row also failed on merge-queue gate branches.
        (3, 4, 5, 5, 48, 5, "failure", 100, 50, BrokenTestState.BREAKING_MASTER),
        # These two rows failed only on merge-queue gate branches.
        (0, 1, 0, 5, 2, 1, None, 0, None, BrokenTestState.BLOCKING_MERGE_QUEUE),
        (0, 3, 0, 5, 5, 4, None, 0, None, BrokenTestState.BLOCKING_MERGE_QUEUE),
        # These two rows also failed on ordinary PR branches, so the gate hit does not set the state.
        (0, 1, 6, 100, 48, 3, None, 0, None, BrokenTestState.FLAKY),
        (0, 1, 6, 5, 5, 4, None, 0, None, BrokenTestState.NOVEL_BURST),
        (0, 0, 5, 5, 5, 4, None, 0, None, BrokenTestState.NOVEL_BURST),
        # The green run finished after the last trunk failure (100 < 1000).
        (2, 0, 3, 40, 100, 3, "success", 1000, 100, BrokenTestState.POTENTIALLY_RESOLVED),
        # The green run finished before the last trunk failure (1000 > 100).
        (2, 0, 3, 40, 100, 3, "success", 100, 1000, BrokenTestState.FLAKY),
        (0, 0, 5, 100, 48, 3, None, 0, None, BrokenTestState.FLAKY),
        # This row hit trunk, but the job has no status.
        (3, 0, 5, 100, 48, 3, None, 100, None, BrokenTestState.FLAKY),
        (0, 0, 2, 5, 2, 1, None, 0, None, BrokenTestState.PR_ONLY),
        # Only 2 branches, and the span is within a day.
        (0, 0, 3, 5, 10, 2, None, 0, None, BrokenTestState.PR_ONLY),
    ],
)
def test_classify_states(
    master_hits: int,
    queue_hits: int,
    pr_hits: int,
    age_hours: int,
    span_hours: int,
    branches: int,
    latest_conclusion: str | None,
    last_master_hit_age: int,
    latest_completed_age: int | None,
    expected: BrokenTestState,
) -> None:
    assert (
        _classify(
            master_hits=master_hits,
            merge_queue_hits=queue_hits,
            pr_branch_hits=pr_hits,
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
    rows = [
        ("fp", 0, 8),
        ("fp", 1, 6),
        ("fp", 23, 1),
        ("fp", 24, 99),
        ("other", 0, 3),
    ]
    series = _sparklines_by_fingerprint(rows)

    assert len(series["fp"]) == BROKEN_TEST_SPARKLINE_HOURS
    assert series["fp"][BROKEN_TEST_SPARKLINE_HOURS - 1] == 8
    assert series["fp"][BROKEN_TEST_SPARKLINE_HOURS - 2] == 6
    assert series["fp"][0] == 1
    assert sum(series["fp"]) == 15
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
    merge_queue_hits=0,
    pr_branch_hits=1,
):
    # The column order mirrors _FINGERPRINTS_SELECT.
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
        merge_queue_hits,
        pr_branch_hits,
        "PostHog/posthog",
        latest_run_id,
        "some-branch",
        workflow_name,
        last_master_hit_age,
        None,
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
        return SimpleNamespace(results=[(*row, "github_actions") for row in master_rows])

    curated.run.side_effect = run_side_effect
    return query_broken_tests(
        curated=curated,
        date_from=datetime(2026, 7, 13, tzinfo=UTC),
        hourly_from=datetime(2026, 7, 14, tzinfo=UTC),
        window_days=2,
        limit=limit,
    )


def test_query_joins_master_status_ranks_by_severity_and_attaches_trend():
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
    assert result.rows[0].trend_24h[-1] == 5
    assert result.rows[0].trend_24h[-2] == 2
    assert result.rows[1].trend_24h == [0] * BROKEN_TEST_SPARKLINE_HOURS


def test_query_keys_master_status_by_workflow_not_just_job_name():
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
    curated.run.assert_not_called()


def test_build_query_embeds_the_failures_view():
    # The fingerprint scan must embed the ci_failures builder as a subquery and never name the managed view.
    assert "engineering_analytics_ci_failures" not in module._FINGERPRINTS_SELECT


class TestBrokenTestsQueryOverClickHouse(ClickhouseTestMixin, BaseTest):
    def _insert_logs(self, rows: list[dict[str, Any]]) -> None:
        payload = "".join(json.dumps({"team_id": self.team.id, **row}) + "\n" for row in rows)
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow\n{payload}")

    def _failure_log(self, *, repo: str, test_id: str, branch: str = "master") -> dict[str, Any]:
        # attributes_map_str keys carry the "__str" suffix the logs table strips for the queryable map.
        return {
            "timestamp": "2026-07-10 12:00:00.000000",
            "body": f"FAILED {test_id} - AssertionError: boom",
            "service_name": CI_LOGS_SERVICE_NAME,
            "attributes_map_str": {
                "repo__str": repo,
                "branch__str": branch,
                "head_sha__str": "abc123",
                "workflow_name__str": "Backend CI",
                "job_name__str": "test (1)",
                "run_id__str": "100",
                "conclusion__str": "failure",
            },
        }

    def _source(self) -> CuratedGitHubSource:
        # workflow_jobs=None makes jobs_source() return None, so the master-status query is skipped.
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
        # lower(repo) in WHERE must bind to the column and not to the any(repo) alias.
        assert [row.test_id for row in result.rows] == ["posthog/api/test_foo.py::test_bar"]
        assert result.rows[0].repo == "PostHog/posthog"

    @parameterized.expand(
        [
            # The capped read keeps the test that failed on more branches.
            ("unfiltered", None, None, ["posthog/api/test_foo.py::test_bar"], 2),
            ("test_substring", "TEST_BAZ", None, ["posthog/api/test_foo.py::test_baz"], 1),
            ("branch", None, "feature-y", ["posthog/api/test_foo.py::test_baz"], 1),
            ("branch_keeps_other_branch_counts", None, "feature-x", ["posthog/api/test_foo.py::test_bar"], 2),
        ]
    )
    def test_filters_apply_before_the_cap(
        self, _name: str, test: str | None, branch: str | None, expected: list[str], expected_branches: int
    ) -> None:
        bar, baz = "posthog/api/test_foo.py::test_bar", "posthog/api/test_foo.py::test_baz"
        self._insert_logs(
            [
                self._failure_log(repo="PostHog/posthog", test_id=bar, branch="master"),
                self._failure_log(repo="PostHog/posthog", test_id=bar, branch="feature-x"),
                self._failure_log(repo="PostHog/posthog", test_id=baz, branch="feature-y"),
            ]
        )
        result = query_broken_tests(
            curated=self._source(),
            date_from=datetime(2026, 7, 9, tzinfo=UTC),
            hourly_from=datetime(2026, 7, 9, tzinfo=UTC),
            window_days=2,
            limit=1,
            test=test,
            branch=branch,
        )
        assert [row.test_id for row in result.rows] == expected
        assert result.rows[0].branches == expected_branches
