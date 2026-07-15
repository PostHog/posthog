from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.engineering_analytics.backend.logic.queries.flaky_tests import _selector_from_nodeid
from products.engineering_analytics.backend.tests.test_views import connect_github_source_without_data
from products.warehouse_sources.backend.facade.models import ExternalDataSource

T_DEDUPED_FLAKE = "posthog/api/test/test_deduped/TestDeduped::test_retry"
T_DEDUPED_SELECTOR = "posthog/api/test/test_deduped.py::TestDeduped::test_retry"
T_INTERLEAVED = "posthog/api/test/test_interleaved/TestInterleaved::test_changes_outcome"
T_REGRESSION = "posthog/api/test/test_regression/TestRegression::test_consistent_failure"
T_TWO_PR_REGRESSION = "posthog/api/test/test_two_prs/TestTwoPRs::test_consistent_failure"
T_STALE = "posthog/api/test/test_stale/TestStale::test_old_retry"
T_RESOLVED = "posthog/api/test/test_resolved/TestResolved::test_fixed"
T_MASTER = "posthog/api/test/test_master/TestMaster::test_breaks_trunk"
T_QUARANTINED = "posthog/api/test/test_quarantined/TestQuarantined::test_still_fails"
T_TIE_A = "posthog/api/test/test_tie_a/TestTie::test_retry"
T_TIE_B = "posthog/api/test/test_tie_b/TestTie::test_retry"
T_FOREIGN = "posthog/api/test/test_foreign/TestForeign::test_retry"
T_OTHER_REPO = "posthog/api/test/test_other_repo/TestOtherRepo::test_retry"


class TestFlakyTestsAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        connect_github_source_without_data(cls.team, prefix="flaky", repository="PostHog/posthog")
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

        now = datetime.now(UTC).replace(microsecond=0)
        recent = now - timedelta(hours=2)
        earlier = now - timedelta(days=2)
        oldest_active = now - timedelta(days=2, hours=12)
        stale = now - timedelta(days=4)

        rows = [
            # Duplicate spans from one run attempt count once. A second retrying run makes this a
            # confirmed flake with two affected runs, not three spans.
            cls._span(1, T_DEDUPED_FLAKE, "rerun_passed", ts=recent, run_id="100", selector=T_DEDUPED_SELECTOR),
            cls._span(2, T_DEDUPED_FLAKE, "rerun_passed", ts=recent, run_id="100", selector=T_DEDUPED_SELECTOR),
            cls._span(3, T_DEDUPED_FLAKE, "rerun_passed", ts=earlier, run_id="101", selector=T_DEDUPED_SELECTOR),
            # Pass, failure, pass across distinct attempts is observed interleaving, so it is a
            # confirmed flake even without automatic retries.
            cls._span(4, T_INTERLEAVED, "passed", ts=oldest_active, run_id="200"),
            cls._span(5, T_INTERLEAVED, "failed", ts=earlier, run_id="201", pr="201", branch="feature/a"),
            cls._span(6, T_INTERLEAVED, "passed", ts=recent, run_id="202"),
            # Failures across PRs without recovery are a suspected regression, not a flake.
            cls._span(7, T_REGRESSION, "failed", ts=earlier, run_id="300", pr="301", branch="feature/a"),
            cls._span(8, T_REGRESSION, "error", ts=earlier, run_id="301", pr="302", branch="feature/b"),
            cls._span(9, T_REGRESSION, "failed", ts=recent, run_id="302", pr="303", branch="feature/c"),
            cls._span(10, T_TWO_PR_REGRESSION, "failed", ts=recent, run_id="310", pr="311", branch="feature/a"),
            cls._span(11, T_TWO_PR_REGRESSION, "failed", ts=recent, run_id="311", pr="312", branch="feature/b"),
            # A recent master-only failure is actionable even without a retry or PR number.
            cls._span(12, T_MASTER, "failed", ts=recent, run_id="400", branch="master"),
            # Xfailed runs are separated as already quarantined.
            cls._span(13, T_QUARANTINED, "xfailed", ts=recent, run_id="500", branch="master"),
            # A stale retry spike stays outside the active queue even in a wider evidence window.
            cls._span(14, T_STALE, "rerun_passed", ts=stale, run_id="600", pr="601", branch="feature/stale"),
            # A failure followed by a recorded pass, without interleaving, is a resolved streak.
            cls._span(15, T_RESOLVED, "failed", ts=earlier, run_id="700", pr="701", branch="feature/fix"),
            cls._span(16, T_RESOLVED, "passed", ts=recent, run_id="701", branch="feature/fix"),
            # Identical evidence uses nodeid as the deterministic final tiebreaker.
            cls._span(17, T_TIE_B, "rerun_passed", ts=recent, run_id="800", pr="801", branch="feature/tie"),
            cls._span(18, T_TIE_A, "rerun_passed", ts=recent, run_id="801", pr="802", branch="feature/tie"),
            cls._span(19, T_FOREIGN, "rerun_passed", ts=recent, run_id="900", service="other-service"),
            cls._span(20, T_OTHER_REPO, "rerun_passed", ts=recent, run_id="901", repo="PostHog/posthog.com"),
            cls._span(21, "Backend CI / core (1)", None, ts=recent, run_id="902"),
        ]
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
            "resource_attributes) VALUES " + ",".join(rows)
        )

    @classmethod
    def tearDownClass(cls) -> None:
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    @classmethod
    def _span(
        cls,
        index: int,
        name: str,
        outcome: str | None,
        *,
        ts: datetime,
        run_id: str,
        run_attempt: str = "1",
        pr: str = "",
        branch: str = "",
        selector: str = "",
        service: str = "ci-backend",
        repo: str = "PostHog/posthog",
    ) -> str:
        attr_pairs = ([f"'test.outcome__str', '{outcome}'"] if outcome else []) + (
            [f"'test.selector__str', '{selector}'"] if selector else []
        )
        attrs = f"map({', '.join(attr_pairs)})" if attr_pairs else "map()"
        resource_pairs = [
            f"'{key}', '{value}'"
            for key, value in (
                ("ci.run_id", run_id),
                ("ci.run_attempt", run_attempt),
                ("ci.pr_number", pr),
                ("ci.branch", branch),
                ("ci.repository", repo),
            )
            if value
        ]
        resource = f"map({', '.join(resource_pairs)})"
        stamp = ts.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"('uuid-{index}', {cls.team.id}, 'trace-{index}', 'span-{index}', 'parent', '{name}', 1, "
            f"'{stamp}', '{stamp}', '{stamp}', 0, '{service}', {attrs}, {resource})"
        )

    def _get(self, **params: str) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/flaky_tests/", params)
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def test_deduplicates_run_attempts_and_exposes_recovery_evidence(self) -> None:
        rows = {item["nodeid"]: item for item in self._get()["items"]}

        deduped = rows[T_DEDUPED_FLAKE]
        assert deduped["classification"] == "confirmed_flake"
        assert deduped["recommendation"] == "deflake"
        assert deduped["selector"] == T_DEDUPED_SELECTOR
        assert deduped["affected_run_count"] == 2
        assert deduped["rerun_recovery_run_count"] == 2
        assert deduped["failed_run_count"] == 0

        interleaved = rows[T_INTERLEAVED]
        assert interleaved["classification"] == "confirmed_flake"
        assert interleaved["has_interleaved_runs"] is True
        assert interleaved["recorded_pass_run_count"] == 2
        assert interleaved["failed_run_count"] == 1
        assert interleaved["last_recorded_execution_at"] > interleaved["last_signal_at"]

    def test_separates_regressions_quarantines_and_master_failures(self) -> None:
        rows = {item["nodeid"]: item for item in self._get()["items"]}

        regression = rows[T_REGRESSION]
        assert regression["classification"] == "suspected_regression"
        assert regression["recommendation"] == "investigate_regression"
        assert regression["affected_run_count"] == 3
        assert regression["affected_pr_count"] == 3

        master = rows[T_MASTER]
        assert master["classification"] == "suspected_regression"
        assert master["master_failed_run_count"] == 1
        assert master["affected_pr_count"] == 0

        quarantined = rows[T_QUARANTINED]
        assert quarantined["classification"] == "quarantined"
        assert quarantined["recommendation"] == "deflake"
        assert quarantined["quarantined_failed_run_count"] == 1

    def test_stale_and_resolved_streaks_do_not_dominate(self) -> None:
        nodeids = {item["nodeid"] for item in self._get(date_from="-30d")["items"]}
        assert T_STALE not in nodeids
        assert T_RESOLVED not in nodeids

    def test_ranking_ties_are_deterministic(self) -> None:
        nodeids = [item["nodeid"] for item in self._get()["items"]]
        assert nodeids.index(T_TIE_A) < nodeids.index(T_TIE_B)

    def test_min_failed_prs_controls_regression_threshold(self) -> None:
        default_nodeids = {item["nodeid"] for item in self._get()["items"]}
        lower_nodeids = {item["nodeid"] for item in self._get(min_failed_prs="2")["items"]}
        assert T_TWO_PR_REGRESSION not in default_nodeids
        assert T_TWO_PR_REGRESSION in lower_nodeids

    def test_source_without_repository_fails_closed(self) -> None:
        ExternalDataSource.objects.filter(team_id=self.team.id).update(job_inputs={})
        data = self._get()
        assert data["items"] == []
        assert data["truncated"] is False

    def test_limit_caps_and_flags_truncation(self) -> None:
        data = self._get(limit="1")
        assert len(data["items"]) == 1
        assert data["truncated"] is True
        assert data["limit"] == 1

    @parameterized.expand(
        [
            ("window_over_30_days", {"date_from": "-45d"}),
            ("reversed_window", {"date_from": "-1d", "date_to": "-5d"}),
            ("zero_min_rerun_passes", {"min_rerun_passes": "0"}),
            ("zero_min_failed_prs", {"min_failed_prs": "0"}),
            ("zero_limit", {"limit": "0"}),
            ("oversized_limit", {"limit": "201"}),
            ("non_integer_threshold", {"min_failed_prs": "lots"}),
        ]
    )
    def test_invalid_params_return_400(self, _name: str, params: dict) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/flaky_tests/", params)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content


@pytest.mark.parametrize(
    "nodeid,expected",
    [
        ("posthog/api/test/test_event/TestEvents::test_x", "posthog/api/test/test_event.py::TestEvents::test_x"),
        ("posthog/tasks/test/test_calc::test_sum", "posthog/tasks/test/test_calc.py::test_sum"),
        ("posthog/test/test_a/TestOuter/TestInner::test_x", "posthog/test/test_a.py::TestOuter::TestInner::test_x"),
        ("test_bare", "test_bare"),
    ],
)
def test_selector_from_nodeid(nodeid: str, expected: str) -> None:
    assert _selector_from_nodeid(nodeid) == expected
