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

T_RERUN_RECOVERY = "posthog/api/test/test_rerun/TestRerun::test_green_on_attempt_2"
T_RERUN_SELECTOR = "posthog/api/test/test_rerun.py::TestRerun::test_green_on_attempt_2"
T_STALE_REREPORT = "posthog/api/test/test_stale/TestStale::test_reported_twice"
T_MATRIX_LEGS = "posthog/api/test/test_legs/TestLegs::test_one_leg_fails"
T_CROSS_RUN_PASS = "posthog/api/test/test_cross/TestCross::test_passes_in_another_run"
T_IN_JOB_RETRY = "posthog/api/test/test_injob/TestInJob::test_pytest_retry"
T_THREE_PRS = "posthog/api/test/test_three/TestThree::test_fails_on_three_prs"
T_TWO_PRS = "posthog/api/test/test_two/TestTwo::test_fails_on_two_prs"
T_MASTER = "posthog/api/test/test_master/TestMaster::test_breaks_trunk"
T_QUARANTINED = "posthog/api/test/test_quarantined/TestQuarantined::test_still_fails"
T_OLD = "posthog/api/test/test_old/TestOld::test_old_flake"
T_TIE_A = "posthog/api/test/test_tie_a/TestTie::test_retry"
T_TIE_B = "posthog/api/test/test_tie_b/TestTie::test_retry"
T_FOREIGN = "posthog/api/test/test_foreign/TestForeign::test_other_service"
T_OTHER_REPO = "posthog/api/test/test_other_repo/TestOtherRepo::test_flaky"


class TestFlakyTestsAPI(ClickhouseTestMixin, APIBaseTest):
    # The aggregation, qualification (HAVING), and ranking all live in the HogQL query, so the
    # regressions worth catching only surface against real seeded trace_spans rows.

    # ClickhouseTestMixin flips this off (per-test teams); back on so one class-level team can
    # key the class-level span seed.
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
        recent = now - timedelta(days=1)
        earlier = now - timedelta(days=2)
        # Inside a -30d window but outside the -7d default.
        old = now - timedelta(days=10)

        rows = [
            # Failed on attempt 1, green on the re-run: one commit, both outcomes. The emitter
            # stamped test.selector here, so it wins over the nodeid reconstruction.
            cls._span(1, T_RERUN_RECOVERY, "failed", ts=earlier, run="100", branch="master", selector=T_RERUN_SELECTOR),
            cls._span(2, T_RERUN_RECOVERY, "passed", ts=recent, run="100", attempt="2", branch="master"),
            # A re-run re-reports the shards it didn't re-execute, so the same failure arrives twice
            # under two attempts. One run, one failure.
            cls._span(3, T_STALE_REREPORT, "failed", ts=earlier, run="200", branch="master"),
            cls._span(4, T_STALE_REREPORT, "failed", ts=earlier, run="200", attempt="2", branch="master"),
            # Attempt 2 re-reports a failing leg and a passing leg together. The failure wins.
            cls._span(5, T_MATRIX_LEGS, "failed", ts=earlier, run="250", branch="master"),
            cls._span(6, T_MATRIX_LEGS, "failed", ts=recent, run="250", attempt="2", branch="master"),
            cls._span(7, T_MATRIX_LEGS, "passed", ts=recent, run="250", attempt="2", branch="master"),
            # A pass in a different run is a different commit and proves nothing.
            cls._span(8, T_CROSS_RUN_PASS, "failed", ts=earlier, run="300", branch="master"),
            cls._span(9, T_CROSS_RUN_PASS, "passed", ts=recent, run="301", attempt="2", branch="master"),
            # In-job pytest retry: the same proof from a lane that runs with --reruns.
            cls._span(10, T_IN_JOB_RETRY, "rerun_passed", ts=recent, run="400", pr="401", branch="f1"),
            # Failures across 3 distinct PRs, no recovery: qualifies on blast radius alone.
            cls._span(11, T_THREE_PRS, "failed", ts=earlier, run="500", pr="501", branch="f1"),
            cls._span(12, T_THREE_PRS, "failed", ts=earlier, run="501", pr="502", branch="f2"),
            cls._span(13, T_THREE_PRS, "error", ts=recent, run="502", pr="503", branch="f3"),
            # Only 2 distinct PRs: below the default bar, reachable via min_failed_prs=2.
            cls._span(14, T_TWO_PRS, "failed", ts=recent, run="600", pr="601", branch="x1"),
            cls._span(15, T_TWO_PRS, "failed", ts=recent, run="601", pr="602", branch="x2"),
            # A master failure is actionable with no PR and no recovery.
            cls._span(16, T_MASTER, "failed", ts=recent, run="700", branch="master"),
            # xfail on master: quarantined, and never counted as a master failure.
            cls._span(17, T_QUARANTINED, "xfailed", ts=recent, run="800", branch="master"),
            # Signal outside the default window.
            cls._span(18, T_OLD, "rerun_passed", ts=old, run="900", pr="901", branch="old1"),
            # Identical evidence: nodeid is the deterministic final tiebreaker.
            cls._span(19, T_TIE_B, "rerun_passed", ts=recent, run="1000", pr="1001", branch="tie"),
            cls._span(20, T_TIE_A, "rerun_passed", ts=recent, run="1001", pr="1002", branch="tie"),
            # Would qualify on signal alone, but a non-CI service must never reach the queue.
            cls._span(21, T_FOREIGN, "rerun_passed", ts=recent, run="1100", pr="1101", service="other-service"),
            # Would qualify on signal alone, but belongs to another connected repository.
            cls._span(22, T_OTHER_REPO, "rerun_passed", ts=recent, run="1200", pr="1201", repo="PostHog/posthog.com"),
            # A job-root span carries no test.outcome and must never become a row.
            cls._span(23, "Backend CI / core (1)", None, ts=recent, run="1300", branch="master"),
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
        run: str,
        attempt: str = "1",
        pr: str = "",
        branch: str = "",
        selector: str = "",
        service: str = "ci-backend",
        repo: str = "PostHog/posthog",
    ) -> str:
        # Physical attributes carry a type suffix ('test.outcome__str'); the `attributes` ALIAS
        # column strips it. Resource attributes are stored as-is.
        attr_pairs = ([f"'test.outcome__str', '{outcome}'"] if outcome else []) + (
            [f"'test.selector__str', '{selector}'"] if selector else []
        )
        attrs = f"map({', '.join(attr_pairs)})" if attr_pairs else "map()"
        resource_pairs = [
            f"'{key}', '{value}'"
            for key, value in (
                ("ci.run_id", run),
                ("ci.run_attempt", attempt),
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

    def _rows(self, **params: str) -> dict[str, dict]:
        return {item["nodeid"]: item for item in self._get(**params)["items"]}

    def test_default_window_qualifies_only_actionable_tests(self) -> None:
        data = self._get()

        # The 2-PR test is below the bar; the out-of-window, foreign-service, other-repo, and
        # outcome-less job-root spans must never qualify.
        assert {row["nodeid"] for row in data["items"]} == {
            T_RERUN_RECOVERY,
            T_STALE_REREPORT,
            T_MATRIX_LEGS,
            T_CROSS_RUN_PASS,
            T_IN_JOB_RETRY,
            T_THREE_PRS,
            T_MASTER,
            T_QUARANTINED,
            T_TIE_A,
            T_TIE_B,
        }
        assert data["truncated"] is False
        assert data["limit"] == 50

    @parameterized.expand(
        [
            ("recovered_on_rerun_attempt", T_RERUN_RECOVERY, "confirmed_flake"),
            ("recovered_via_in_job_retry", T_IN_JOB_RETRY, "confirmed_flake"),
            # The pass is in another run, so it is another commit and proves nothing.
            ("pass_in_a_different_run", T_CROSS_RUN_PASS, "suspected_regression"),
            # A failing leg and a passing leg in one attempt is not a recovery.
            ("pass_in_another_matrix_leg", T_MATRIX_LEGS, "suspected_regression"),
            ("no_recovery_recorded", T_THREE_PRS, "suspected_regression"),
            ("failing_while_xfailed", T_QUARANTINED, "quarantined"),
        ]
    )
    def test_classification_follows_same_commit_recovery(self, _name: str, nodeid: str, expected: str) -> None:
        assert self._rows()[nodeid]["classification"] == expected

    def test_evidence_is_counted_once_per_run(self) -> None:
        rows = self._rows()

        # Two attempts of one run, both reporting the same failure: one run, one failure, and the
        # re-report is not mistaken for a second occurrence.
        stale = rows[T_STALE_REREPORT]
        assert stale["failed_run_count"] == 1
        assert stale["same_commit_recovery_run_count"] == 0
        assert stale["master_failed_run_count"] == 1

        recovered = rows[T_RERUN_RECOVERY]
        assert recovered["same_commit_recovery_run_count"] == 1
        assert recovered["failed_run_count"] == 1
        assert recovered["selector"] == T_RERUN_SELECTOR
        # The attempt-2 pass is not a signal, so recency still points at the failure.
        assert recovered["last_signal_at"] < rows[T_MASTER]["last_signal_at"]

        three_prs = rows[T_THREE_PRS]
        assert (three_prs["failed_run_count"], three_prs["failed_pr_count"]) == (3, 3)
        # Falls back to the nodeid reconstruction: no emitted test.selector.
        assert three_prs["selector"] == "posthog/api/test/test_three.py::TestThree::test_fails_on_three_prs"

        master = rows[T_MASTER]
        assert (master["master_failed_run_count"], master["failed_pr_count"]) == (1, 0)

        # An xfail is not a failure, so it drives neither count.
        quarantined = rows[T_QUARANTINED]
        assert quarantined["quarantined_failed_run_count"] == 1
        assert (quarantined["failed_run_count"], quarantined["master_failed_run_count"]) == (0, 0)

    def test_ranking_leads_with_trunk_breakage_and_breaks_ties_on_nodeid(self) -> None:
        nodeids = [item["nodeid"] for item in self._get()["items"]]

        # Master failures outrank PR-only evidence however many PRs it hit.
        assert nodeids.index(T_MASTER) < nodeids.index(T_THREE_PRS)
        assert nodeids.index(T_TIE_A) < nodeids.index(T_TIE_B)

    def test_min_failed_prs_controls_the_no_recovery_threshold(self) -> None:
        assert T_TWO_PRS not in self._rows()
        assert T_TWO_PRS in self._rows(min_failed_prs="2")

    def test_wider_window_includes_older_signal(self) -> None:
        assert T_OLD in self._rows(date_from="-30d")

    def test_source_without_repository_fails_closed(self) -> None:
        # A source with no repository identity can't be scoped, so the queue must be empty rather
        # than leak every connected repository's spans (the qualifying rows are still seeded, so a
        # fail-open regression would return them).
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
            ("zero_min_failed_prs", {"min_failed_prs": "0"}),
            ("zero_limit", {"limit": "0"}),
            ("oversized_limit", {"limit": "201"}),
            ("non_integer_threshold", {"min_failed_prs": "lots"}),
        ]
    )
    def test_invalid_params_return_400(self, _name: str, params: dict) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/flaky_tests/", params)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content


# A wrong split yields a selector CI's quarantine matching would silently never hit. This is the
# fallback reconstruction for spans emitted before the CI reporter stamped test.selector.
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
