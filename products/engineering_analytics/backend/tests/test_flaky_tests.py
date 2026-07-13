from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.engineering_analytics.backend.logic.queries.flaky_tests import _selector_from_nodeid
from products.engineering_analytics.backend.tests.test_views import connect_github_source_without_data

T_PRS = "posthog/api/test/test_prs/TestPRs::test_flaky_on_prs"
T_RERUN = "posthog/api/test/test_rerun/TestRerun::test_pass_on_retry"
T_RERUN_SELECTOR = "posthog/api/test/test_rerun.py::TestRerun::test_pass_on_retry"
T_TWO_PRS = "posthog/api/test/test_two/TestTwo::test_two_prs"
T_XFAIL_ONLY = "posthog/api/test/test_xf/TestXF::test_xfail_only"
T_OLD = "posthog/api/test/test_old/TestOld::test_old_flake"
T_FOREIGN = "posthog/api/test/test_foreign/TestForeign::test_other_service"


class TestFlakyTestsAPI(ClickhouseTestMixin, APIBaseTest):
    # The aggregation, qualification (HAVING), and ranking all live in the HogQL query, so the
    # regressions worth catching only surface against real seeded trace_spans rows — same setup
    # pattern as the tracing product's query tests.

    # ClickhouseTestMixin flips this off (per-test teams); back on so one class-level team can
    # key the class-level span seed.
    CLASS_DATA_LEVEL_SETUP = True

    recent: datetime

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        connect_github_source_without_data(cls.team, prefix="flaky")
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

        now = datetime.now(UTC).replace(microsecond=0)
        cls.recent = now - timedelta(days=1)
        earlier = now - timedelta(days=2)
        # Inside a -30d window but outside the -7d default.
        old = now - timedelta(days=10)

        rows = [
            # Qualifies via distinct PRs (3): 4 failed + 1 error spans, one PR hit twice (dedup),
            # one master error with no PR (counts as a failure, not a PR), plus one xfail.
            cls._span(1, T_PRS, "failed", ts=earlier, pr="101", branch="f1"),
            cls._span(2, T_PRS, "failed", ts=earlier, pr="101", branch="f1"),
            cls._span(3, T_PRS, "failed", ts=earlier, pr="102", branch="f2"),
            cls._span(4, T_PRS, "error", ts=earlier, pr="103", branch="f3"),
            cls._span(5, T_PRS, "error", ts=earlier, branch="master"),
            cls._span(6, T_PRS, "xfailed", ts=cls.recent, branch="master"),
            # Qualifies via pass-on-retry; the passing span must not leak into any count. The
            # emitter stamped test.selector here, so it wins over the nodeid reconstruction.
            cls._span(7, T_RERUN, "rerun_passed", ts=cls.recent, pr="201", branch="r1", selector=T_RERUN_SELECTOR),
            cls._span(8, T_RERUN, "rerun_passed", ts=cls.recent, branch="master", selector=T_RERUN_SELECTOR),
            cls._span(9, T_RERUN, "passed", ts=cls.recent, branch="pass-branch"),
            # Fails on only 2 distinct PRs — below the default bar, reachable via min_failed_prs=2.
            cls._span(10, T_TWO_PRS, "failed", ts=cls.recent, pr="301", branch="x1"),
            cls._span(11, T_TWO_PRS, "failed", ts=cls.recent, pr="302", branch="x2"),
            cls._span(12, T_TWO_PRS, "failed", ts=cls.recent, pr="302", branch="x2"),
            # xfail alone is already-quarantined noise, never a qualifier.
            cls._span(13, T_XFAIL_ONLY, "xfailed", ts=cls.recent, branch="master"),
            cls._span(14, T_XFAIL_ONLY, "xfailed", ts=cls.recent, branch="master"),
            # Signal outside the default window.
            cls._span(15, T_OLD, "rerun_passed", ts=old, pr="401", branch="old1"),
            # Would qualify on signal alone, but a non-CI service must never reach the leaderboard.
            cls._span(17, T_FOREIGN, "rerun_passed", ts=cls.recent, pr="501", branch="s1", service="other-service"),
            # A job-root span carries no test.outcome and must never become a leaderboard row.
            cls._span(16, "Backend CI / core (1)", None, ts=cls.recent, branch="master"),
        ]
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
            "resource_attributes) VALUES " + ",".join(rows)
        )

    @classmethod
    def tearDownClass(cls):
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())
        super().tearDownClass()

    @classmethod
    def _span(
        cls,
        i: int,
        name: str,
        outcome: str | None,
        *,
        ts: datetime,
        pr: str = "",
        branch: str = "",
        selector: str = "",
        service: str = "ci-backend",
    ) -> str:
        # Physical attributes carry a type suffix ('test.outcome__str'); the `attributes` ALIAS
        # column strips it. Resource attributes are stored as-is.
        attr_pairs = ([f"'test.outcome__str', '{outcome}'"] if outcome else []) + (
            [f"'test.selector__str', '{selector}'"] if selector else []
        )
        attrs = f"map({', '.join(attr_pairs)})" if attr_pairs else "map()"
        resource_pairs = ([f"'ci.pr_number', '{pr}'"] if pr else []) + ([f"'ci.branch', '{branch}'"] if branch else [])
        resource = f"map({', '.join(resource_pairs)})" if resource_pairs else "map()"
        stamp = ts.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"('uuid-{i}', {cls.team.id}, 'trace-{i}', 'span-{i}', 'parent', '{name}', 1, "
            f"'{stamp}', '{stamp}', '{stamp}', 0, '{service}', {attrs}, {resource})"
        )

    def _get(self, **params: str) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/flaky_tests/", params)
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def test_default_window_qualifies_aggregates_and_ranks(self):
        data = self._get()

        # Only the qualifying tests, strongest signal first (T_PRS scores 3 distinct PRs vs
        # T_RERUN's 2 retries); the 2-PR test, the xfail-only test, the out-of-window test, the
        # outcome-less job-root span, and the foreign-service row are all excluded.
        assert [item["nodeid"] for item in data["items"]] == [T_PRS, T_RERUN]
        assert data["truncated"] is False
        assert data["limit"] == 50

        by_prs, by_rerun = data["items"]
        # T_RERUN carried an emitted test.selector; T_PRS didn't, so it falls back to the nodeid
        # reconstruction (folded '/' → '.py' boundary).
        assert by_rerun["selector"] == T_RERUN_SELECTOR
        assert by_prs["selector"] == "posthog/api/test/test_prs.py::TestPRs::test_flaky_on_prs"
        assert (by_prs["rerun_passed_count"], by_prs["failed_count"], by_prs["failed_pr_count"]) == (0, 5, 3)
        assert (by_prs["branch_count"], by_prs["xfailed_count"]) == (4, 1)
        # max() over the signal spans — the xfail at `recent` is newer than the failures.
        assert by_prs["last_seen_at"].startswith(self.recent.strftime("%Y-%m-%dT%H:%M:%S"))
        assert (by_rerun["rerun_passed_count"], by_rerun["failed_count"], by_rerun["failed_pr_count"]) == (2, 0, 0)
        # 2, not 3: the plain 'passed' span (branch 'pass-branch') is outside the signal set.
        assert (by_rerun["branch_count"], by_rerun["xfailed_count"]) == (2, 0)

    @parameterized.expand(
        [
            # Lowering the PR bar pulls in the 2-PR test; ties on score (2) break on failed_count.
            ("lower_min_failed_prs", {"min_failed_prs": "2"}, [T_PRS, T_TWO_PRS, T_RERUN]),
            # Raising the rerun bar drops the retry-qualified test; T_PRS still qualifies via PRs.
            ("raise_min_rerun_passes", {"min_rerun_passes": "3"}, [T_PRS]),
        ]
    )
    def test_thresholds_are_query_params(self, _name: str, params: dict, expected: list[str]):
        data = self._get(**params)
        assert [item["nodeid"] for item in data["items"]] == expected

    def test_wider_window_includes_older_signal(self):
        data = self._get(date_from="-30d")
        assert T_OLD in [item["nodeid"] for item in data["items"]]

    def test_limit_caps_and_flags_truncation(self):
        data = self._get(limit="1")
        assert [item["nodeid"] for item in data["items"]] == [T_PRS]
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
    def test_invalid_params_return_400(self, _name: str, params: dict):
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/flaky_tests/", params)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content


# A wrong split yields a selector CI's quarantine matching would silently never hit — the fallback
# reconstruction for spans emitted before the CI reporter stamped test.selector.
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
