from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.engineering_analytics.backend.tests._github_fixtures import connect_github_source_without_data
from products.warehouse_sources.backend.facade.models import ExternalDataSource

T_ACROSS_PRS = "posthog/api/test/test_history/TestHistory::test_fails_across_prs"
T_ACROSS_PRS_SELECTOR = "posthog/api/test/test_history.py::TestHistory::test_fails_across_prs"
T_QUARANTINED = "posthog/api/test/test_masked/TestMasked::test_tolerated_failure"
T_MATRIX_LEGS = "posthog/api/test/test_legs/TestLegs::test_fails_in_two_legs"
T_COLLIDING = "shared/identity::test_same_name_in_both_runners"
T_OTHER_REPO = "posthog/api/test/test_other/TestOther::test_other_repo"


class TestTestSignalHistoryAPI(ClickhouseTestMixin, APIBaseTest):
    # The identity match, the run grain, and the window-complete rollup all live in the HogQL query,
    # so the regressions worth catching only surface against real seeded trace_spans rows.

    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        connect_github_source_without_data(cls.team, prefix="history", repository="PostHog/posthog")
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

        now = datetime.now(UTC).replace(microsecond=0)
        recent = now - timedelta(days=1)
        earlier = now - timedelta(days=2)
        earliest = now - timedelta(days=3)
        # Inside a -30d window but outside the -7d default.
        old = now - timedelta(days=10)

        rows = [
            # One test seen on master and on two PRs, one of which recovered on a re-run attempt.
            # Every span carries the emitted selector, so a caller can look the test up either way.
            cls._span(1, T_ACROSS_PRS, "failed", ts=recent, run="10", branch="master"),
            cls._span(2, T_ACROSS_PRS, "failed", ts=earlier, run="11", pr="201", branch="feat-a"),
            cls._span(3, T_ACROSS_PRS, "failed", ts=earliest, run="12", pr="202", branch="feat-b"),
            # The re-run attempt goes green on the same commit, later than every other signal. It is a
            # recovery, not signal, so it must not make run 12 the newest run.
            cls._span(4, T_ACROSS_PRS, "passed", ts=recent, run="12", attempt="2", pr="202", branch="feat-b"),
            cls._span(5, T_ACROSS_PRS, "failed", ts=old, run="13", pr="203", branch="feat-c"),
            # A tolerated failure while quarantine masks the test: quarantined, never a failure.
            cls._span(6, T_QUARANTINED, "xfailed", ts=earlier, run="20", branch="master"),
            # One run fans the test across two stable matrix jobs and both fail. One run, one failure.
            cls._span(7, T_MATRIX_LEGS, "failed", ts=earlier, run="30", branch="master", job="FOSS:1"),
            cls._span(8, T_MATRIX_LEGS, "failed", ts=recent, run="30", branch="master", job="EE:1"),
            # The same identity emitted by both suites: only the runner filter can separate them.
            cls._span(9, T_COLLIDING, "failed", ts=earlier, run="40", pr="401", branch="py"),
            cls._span(10, T_COLLIDING, "failed", ts=earlier, run="41", pr="411", branch="js", service="ci-frontend"),
            # Another connected repository's signal for a test this source must never answer for.
            cls._span(11, T_OTHER_REPO, "failed", ts=earlier, run="50", repo="PostHog/posthog.com"),
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
        outcome: str,
        *,
        ts: datetime,
        run: str,
        attempt: str = "1",
        pr: str = "",
        branch: str = "",
        service: str = "ci-backend",
        repo: str = "PostHog/posthog",
        job: str = "",
    ) -> str:
        # Physical attributes carry a type suffix ('test.outcome__str'); the `attributes` ALIAS column
        # strips it. Resource attributes are stored as-is.
        # Only T_ACROSS_PRS gets a selector that differs from its nodeid, which is what makes the
        # two-identity lookup a real test rather than one string matching itself twice.
        selector = T_ACROSS_PRS_SELECTOR if name == T_ACROSS_PRS else name
        attr_pairs = [f"'test.outcome__str', '{outcome}'", f"'test.selector__str', '{selector}'"]
        if job:
            attr_pairs.append(f"'test.job_key__str', '{job}'")
        attrs = f"map({', '.join(attr_pairs)})"
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

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/engineering_analytics/test_signal_history/"

    def _get(self, test: str, **params: str) -> dict:
        response = self.client.get(self._url(), {"test": test, **params})
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def _runs(self, test: str, **params: str) -> dict[str, dict]:
        return {run["run_id"]: run for run in self._get(test, **params)["runs"]}

    @parameterized.expand([("by_nodeid", T_ACROSS_PRS), ("by_selector", T_ACROSS_PRS_SELECTOR)])
    def test_a_test_resolves_from_either_identity(self, _name: str, test: str) -> None:
        data = self._get(test)

        # The queue hands out both fields, so either must reach the same history.
        assert data["nodeid"] == T_ACROSS_PRS
        assert data["selector"] == T_ACROSS_PRS_SELECTOR
        assert data["runner"] == "pytest"
        # Newest first, and the run whose re-run attempt passed last is still the oldest signal:
        # a recovery pass is not signal, so it never moves a run's recency.
        assert [run["run_id"] for run in data["runs"]] == ["10", "11", "12"]

    def test_run_rows_report_where_each_run_ran_and_what_it_proved(self) -> None:
        runs = self._runs(T_ACROSS_PRS)

        # A master push carries no PR association, and 0 would read as PR #0.
        assert runs["10"]["pr_number"] is None
        assert (runs["10"]["branch"], runs["10"]["failed"], runs["10"]["recovered"]) == ("master", True, False)
        assert (runs["11"]["pr_number"], runs["11"]["branch"]) == (201, "feat-a")
        assert (runs["12"]["pr_number"], runs["12"]["failed"], runs["12"]["recovered"]) == (202, True, True)
        assert [run["quarantined"] for run in runs.values()] == [False, False, False]

        masked = self._runs(T_QUARANTINED)["20"]
        # An xfail is a tolerated failure, not a failure.
        assert (masked["quarantined"], masked["failed"], masked["recovered"]) == (True, False, False)

    @parameterized.expand(
        [
            (
                "recovered_on_a_rerun_attempt",
                T_ACROSS_PRS,
                "confirmed_flake",
                {
                    "same_commit_recovery_run_count": 1,
                    "failed_run_count": 3,
                    "failed_pr_count": 2,
                    "master_failed_run_count": 1,
                    "quarantined_failed_run_count": 0,
                },
            ),
            (
                "failing_while_masked",
                T_QUARANTINED,
                "quarantined",
                {
                    "same_commit_recovery_run_count": 0,
                    "failed_run_count": 0,
                    "failed_pr_count": 0,
                    "master_failed_run_count": 0,
                    "quarantined_failed_run_count": 1,
                },
            ),
        ]
    )
    def test_rollup_counts_match_the_queue_definitions(
        self, _name: str, test: str, expected_classification: str, expected_counts: dict[str, int]
    ) -> None:
        data = self._get(test)

        assert data["classification"] == expected_classification
        assert {key: data[key] for key in expected_counts} == expected_counts

    def test_evidence_is_counted_once_per_run(self) -> None:
        data = self._get(T_MATRIX_LEGS)

        # Two failing matrix jobs of one run: one run row, one failure. Span- or job-grain counting
        # would say 2 and double this test's apparent blast radius.
        assert [run["run_id"] for run in data["runs"]] == ["30"]
        assert (data["failed_run_count"], data["master_failed_run_count"]) == (1, 1)
        # Recency is the newest failing leg, not the first one seen.
        assert data["last_signal_at"] == data["runs"][0]["signal_at"]

    def test_counts_stay_window_complete_when_the_run_list_is_truncated(self) -> None:
        data = self._get(T_ACROSS_PRS, limit="1")

        assert (len(data["runs"]), data["truncated"], data["limit"]) == (1, True, 1)
        # The counts are a sibling aggregate of the capped list: page-scoped counts here would
        # disagree with what the test-health queue reports for the same test and window.
        assert (data["failed_run_count"], data["failed_pr_count"]) == (3, 2)
        assert data["same_commit_recovery_run_count"] == 1

    @parameterized.expand([("pytest", "40", "py"), ("jest", "41", "js")])
    def test_runner_filter_separates_a_cross_runner_identity(
        self, runner: str, expected_run: str, expected_branch: str
    ) -> None:
        data = self._get(T_COLLIDING, runner=runner)

        assert data["runner"] == runner
        assert [(run["run_id"], run["branch"]) for run in data["runs"]] == [(expected_run, expected_branch)]
        assert data["failed_run_count"] == 1

    def test_wider_window_includes_older_signal(self) -> None:
        assert "13" not in self._runs(T_ACROSS_PRS)
        assert "13" in self._runs(T_ACROSS_PRS, date_from="-30d")

    def test_unknown_test_returns_an_empty_history(self) -> None:
        data = self._get("posthog/api/test/test_nope/TestNope::test_never_ran")

        # An unknown test is a legitimate empty answer, and a fabricated runner or classification
        # would read as a verdict on a test this window says nothing about.
        assert data["runs"] == []
        assert (data["runner"], data["classification"], data["last_signal_at"]) == (None, None, None)
        assert data["failed_run_count"] == 0
        assert data["nodeid"] == "posthog/api/test/test_nope/TestNope::test_never_ran"

    def test_another_repositorys_history_never_leaks(self) -> None:
        # The spans are seeded and would qualify, but they belong to a different repository.
        assert self._get(T_OTHER_REPO)["runs"] == []

    def test_source_without_repository_fails_closed(self) -> None:
        # Without a repository identity the spans can't be scoped, so the history must be empty
        # rather than answer from every connected repository at once.
        ExternalDataSource.objects.filter(team_id=self.team.id).update(job_inputs={})
        data = self._get(T_ACROSS_PRS)
        assert (data["runs"], data["failed_run_count"], data["truncated"]) == ([], 0, False)

    @parameterized.expand(
        [
            ("missing_test", {}),
            ("blank_test", {"test": "   "}),
            ("unknown_runner", {"test": T_ACROSS_PRS, "runner": "playwright"}),
            ("window_over_30_days", {"test": T_ACROSS_PRS, "date_from": "-45d"}),
            ("reversed_window", {"test": T_ACROSS_PRS, "date_from": "-1d", "date_to": "-5d"}),
            ("zero_limit", {"test": T_ACROSS_PRS, "limit": "0"}),
            ("oversized_limit", {"test": T_ACROSS_PRS, "limit": "201"}),
            ("non_integer_limit", {"test": T_ACROSS_PRS, "limit": "lots"}),
        ]
    )
    def test_invalid_params_return_400(self, _name: str, params: dict) -> None:
        response = self.client.get(self._url(), params)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
