from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.traces.spans import TRACE_SPANS_DISTRIBUTED_TABLE_SQL, TRACE_SPANS_TABLE_SQL

from products.engineering_analytics.backend.tests._github_fixtures import connect_github_source_without_data
from products.warehouse_sources.backend.facade.models import ExternalDataSource

T_REPLAY_PRS = "products/replay/backend/tests/test_snap/TestSnap::test_prs"
T_REPLAY_RERUN = "products/replay/backend/tests/test_playlist/TestPlaylist::test_rerun"
T_EXPORTS_RECOVERED = "products/batch_exports/backend/tests/test_snowflake/TestSnowflake::test_recovered"
T_UNOWNED = "posthog/api/test/test_shared/TestShared::test_unowned"
T_FOREIGN = "posthog/api/test/test_foreign/TestForeign::test_other_service"
T_RESTAMPED = "products/moved/backend/tests/test_moved/TestMoved::test_restamped"
T_PASS_ONLY = "products/quiet/backend/tests/test_quiet/TestQuiet::test_pass_only"
T_FRONTEND = "frontend/src/scenes/example.test.ts::example reports a recent signal"


class TestTeamCIHealthAPI(ClickhouseTestMixin, APIBaseTest):
    # The two-window split, per-(team, nodeid) qualification bar, and unowned bucketing all
    # live in the HogQL rollup, so regressions only surface against real seeded trace_spans
    # rows, same setup pattern as TestFlakyTestsAPI.

    CLASS_DATA_LEVEL_SETUP = True

    current_a: datetime
    current_b: datetime

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        connect_github_source_without_data(cls.team, prefix="teams", repository="PostHog/posthog")
        sync_execute("DROP TABLE IF EXISTS trace_spans_distributed")
        sync_execute("DROP TABLE IF EXISTS trace_spans")
        sync_execute(TRACE_SPANS_TABLE_SQL())
        sync_execute(TRACE_SPANS_DISTRIBUTED_TABLE_SQL())

        now = datetime.now(UTC).replace(microsecond=0)
        # Default window is -14d: current spans sit safely inside it, prior spans safely
        # inside the equal-length twin [-28d, -14d).
        cls.current_a = now - timedelta(days=2)
        cls.current_b = now - timedelta(days=1)
        prior = now - timedelta(days=20)

        rows = [
            cls._catalog(
                100,
                ["batch-exports", "team-replay", "team-zero", "unowned", "@individual-owner"],
                ts=cls.current_b,
            ),
            # team-replay test 1: 3 distinct failed PRs current, no recovery, so a regression, not a
            # flake. Prior has 1 PR, below the bar. One current xfail counts separately and stays out
            # of the slope signal.
            cls._span(1, T_REPLAY_PRS, "failed", ts=cls.current_a, owner="team-replay", run="101", pr="101"),
            cls._span(2, T_REPLAY_PRS, "failed", ts=cls.current_a, owner="team-replay", run="102", pr="102"),
            cls._span(3, T_REPLAY_PRS, "failed", ts=cls.current_a, owner="team-replay", run="103", pr="103"),
            cls._span(4, T_REPLAY_PRS, "xfailed", ts=cls.current_b, owner="team-replay", run="104"),
            cls._span(5, T_REPLAY_PRS, "failed", ts=prior, owner="team-replay", run="105", pr="101"),
            # team-replay test 2 is a proven flake in both windows via in-job pass-on-retry.
            cls._span(6, T_REPLAY_RERUN, "rerun_passed", ts=cls.current_b, owner="team-replay", run="201", pr="201"),
            cls._span(7, T_REPLAY_RERUN, "rerun_passed", ts=prior, owner="team-replay", run="202", pr="202"),
            cls._span(8, T_REPLAY_RERUN, "rerun_passed", ts=prior, owner="team-replay", run="203", pr="203"),
            # batch-exports: unrecovered PR failures in the prior window, then a re-run attempt goes
            # green on the same commit in the current one. The same test moves from regression to
            # proven flake, through the same cross-attempt proof the queue reads.
            cls._span(9, T_EXPORTS_RECOVERED, "failed", ts=prior, owner="batch-exports", run="301", pr="301"),
            cls._span(10, T_EXPORTS_RECOVERED, "failed", ts=prior, owner="batch-exports", run="302", pr="302"),
            cls._span(11, T_EXPORTS_RECOVERED, "failed", ts=prior, owner="batch-exports", run="303", pr="303"),
            cls._span(14, T_EXPORTS_RECOVERED, "failed", ts=cls.current_a, owner="batch-exports", run="304", pr="304"),
            cls._span(
                15,
                T_EXPORTS_RECOVERED,
                "passed",
                ts=cls.current_b,
                owner="batch-exports",
                run="304",
                attempt="2",
                pr="304",
            ),
            # Ownership re-stamp: prior-window failure stamped team-old, current stamped team-new.
            # Each run remains with its capture-time owner.
            cls._span(15, T_RESTAMPED, "failed", ts=prior, owner="team-old", run="601", pr="601"),
            cls._span(16, T_RESTAMPED, "failed", ts=cls.current_b, owner="team-new", run="602", pr="602"),
            # No owner stamp: buckets under the literal 'unowned'.
            cls._span(12, T_UNOWNED, "rerun_passed", ts=cls.current_b, owner="", run="401", pr="401"),
            # A re-run pass with no same-run failure: a shard re-executed alongside the flaky one.
            # It pairs with nothing, so its team must not appear in the roster at all.
            cls._span(
                17, T_PASS_ONLY, "passed", ts=cls.current_b, owner="team-quiet", run="701", attempt="2", pr="701"
            ),
            # A non-CI service must never reach the roster (the scan is fenced by service_name).
            cls._span(
                13,
                T_FOREIGN,
                "rerun_passed",
                ts=cls.current_b,
                owner="ghost-team",
                run="501",
                pr="501",
                service="other",
            ),
            cls._span(
                18,
                T_FRONTEND,
                "rerun_passed",
                ts=cls.current_b,
                owner="team-replay",
                run="801",
                service="ci-frontend",
                framework="jest",
                job="frontend-EE:frontend-EE:1",
            ),
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
        outcome: str,
        *,
        ts: datetime,
        owner: str,
        run: str,
        attempt: str = "1",
        pr: str = "",
        service: str = "ci-backend",
        framework: str = "",
        job: str = "",
    ) -> str:
        attr_pairs = [f"'test.outcome__str', '{outcome}'"]
        if owner:
            attr_pairs.append(f"'test.owner_team__str', '{owner}'")
        if framework:
            attr_pairs.append(f"'test.framework__str', '{framework}'")
        if job:
            attr_pairs.append(f"'test.job_key__str', '{job}'")
        resource_pairs = [
            "'ci.repository', 'PostHog/posthog'",
            f"'ci.run_id', '{run}'",
            f"'ci.run_attempt', '{attempt}'",
        ]
        if pr:
            resource_pairs.append(f"'ci.pr_number', '{pr}'")
        stamp = ts.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"('uuid-{i}', {cls.team.id}, 'trace-{i}', 'span-{i}', 'parent', '{name}', 1, "
            f"'{stamp}', '{stamp}', '{stamp}', 0, '{service}', map({', '.join(attr_pairs)}), "
            f"map({', '.join(resource_pairs)}))"
        )

    @classmethod
    def _catalog(cls, i: int, teams: list[str], *, ts: datetime) -> str:
        teams_json = "[" + ",".join(f'"{team}"' for team in teams) + "]"
        stamp = ts.strftime("%Y-%m-%d %H:%M:%S")
        return (
            f"('uuid-{i}', {cls.team.id}, 'trace-{i}', 'span-{i}', '', 'ownership.catalog', 1, "
            f"'{stamp}', '{stamp}', '{stamp}', 0, 'ci-ownership-catalog', "
            f"map('ownership.primary_teams_json__str', '{teams_json}'), "
            "map('ci.repository', 'PostHog/posthog'))"
        )

    def _get(self, endpoint: str, **params: str) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/{endpoint}/", params)
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def _roster(self) -> dict[str, dict]:
        return {item["owner_team"]: item for item in self._get("team_ci_health")["items"]}

    def test_roster_uses_the_same_flake_proof_as_the_queue(self):
        rows = self._roster()

        # Only the pass-on-retry test is proven flaky. The 3-PR test failed with no recovery, so it
        # is a regression here exactly as it is in the queue.
        replay = rows["team-replay"]
        assert (replay["flaky_test_count"], replay["regression_test_count"]) == (2, 1)
        assert (replay["flaky_test_count_prior"], replay["regression_test_count_prior"]) == (1, 0)
        assert (replay["failed_run_count"], replay["failed_run_count_prior"]) == (3, 1)
        assert (replay["same_commit_recovery_run_count"], replay["same_commit_recovery_run_count_prior"]) == (2, 2)
        assert (replay["quarantined_failed_run_count"], replay["quarantined_failed_run_count_prior"]) == (1, 0)

        assert (rows["unowned"]["flaky_test_count"], rows["unowned"]["same_commit_recovery_run_count"]) == (1, 1)

        # A re-run attempt went green on the same commit, so it is current-window flaky; the prior
        # window's 3 unrecovered PR failures are a regression, not a flake.
        exports = rows["batch-exports"]
        assert (exports["flaky_test_count"], exports["regression_test_count"]) == (1, 0)
        assert (exports["flaky_test_count_prior"], exports["regression_test_count_prior"]) == (0, 1)
        assert (exports["failed_run_count"], exports["failed_run_count_prior"]) == (1, 3)
        assert (exports["same_commit_recovery_run_count"], exports["same_commit_recovery_run_count_prior"]) == (1, 0)

        # The foreign-service span's team must not appear at all.
        assert "ghost-team" not in rows
        # A re-run pass that pairs with no failure is not evidence: no phantom all-zero team row.
        assert "team-quiet" not in rows
        assert rows["team-zero"]["has_test_activity"] is False
        assert rows["team-zero"]["last_seen_at"] is None

    def test_surface_filters_and_all_aggregation_agree(self):
        all_rows = {item["owner_team"]: item for item in self._get("team_ci_health")["items"]}
        backend_rows = {item["owner_team"]: item for item in self._get("team_ci_health", surface="backend")["items"]}
        frontend_rows = {item["owner_team"]: item for item in self._get("team_ci_health", surface="frontend")["items"]}

        assert all_rows["team-replay"]["flaky_test_count"] == 2
        assert backend_rows["team-replay"]["flaky_test_count"] == 1
        assert frontend_rows["team-replay"]["flaky_test_count"] == 1
        assert all_rows["team-replay"]["flaky_test_count"] == (
            backend_rows["team-replay"]["flaky_test_count"] + frontend_rows["team-replay"]["flaky_test_count"]
        )
        assert "unowned" not in frontend_rows
        assert "@individual-owner" not in frontend_rows
        frontend_tests = self._get("team_ci_activity", owner_team="team-replay", surface="frontend")["tests"]
        assert [(test["nodeid"], test["surface"]) for test in frontend_tests] == [(T_FRONTEND, "frontend")]

    def test_restamped_test_preserves_capture_time_owner_in_roster_and_drill_in(self):
        rows = self._roster()

        assert (rows["team-new"]["failed_run_count"], rows["team-new"]["failed_run_count_prior"]) == (1, 0)
        assert (rows["team-old"]["failed_run_count"], rows["team-old"]["failed_run_count_prior"]) == (0, 1)

        assert [
            (t["nodeid"], t["signal_count"], t["signal_count_prior"])
            for t in self._get("team_ci_activity", owner_team="team-new")["tests"]
        ] == [(T_RESTAMPED, 1, 0)]
        assert [
            (t["nodeid"], t["signal_count"], t["signal_count_prior"])
            for t in self._get("team_ci_activity", owner_team="team-old")["tests"]
        ] == [(T_RESTAMPED, 0, 1)]

    def test_activity_scopes_to_team_and_pairs_windows(self):
        data = self._get("team_ci_activity", owner_team="team-replay")

        assert data["owner_team"] == "team-replay"
        # Before/after pairs: ranked by the stronger window, xfail excluded from signal.
        assert [(t["nodeid"], t["signal_count"], t["signal_count_prior"]) for t in data["tests"]] == [
            (T_REPLAY_PRS, 3, 1),
            (T_REPLAY_RERUN, 1, 2),
            (T_FRONTEND, 1, 0),
        ]
        assert not data["truncated_tests"]

    def test_activity_for_unknown_team_is_empty(self):
        data = self._get("team_ci_activity", owner_team="team-nonexistent")
        assert data["tests"] == []

    def test_source_without_repository_degrades_to_no_data(self):
        ExternalDataSource.objects.filter(team_id=self.team.id).update(job_inputs={})

        data = self._get("team_ci_health")

        assert data["items"] == []
        assert data["has_ownership_catalog"] is False
        assert data["ownership_catalog_captured_at"] is None

    def test_activity_requires_owner_team(self):
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/team_ci_activity/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
