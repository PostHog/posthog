from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

import dagster

from posthog.schema import WebStatsBreakdown

from posthog.models import Organization, Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.web_analytics.dags.eager_web_analytics_precompute import (
    BASELINE_BREAKDOWNS,
    BASELINE_WINDOW_DAYS,
    EAGER_FLAG_KEY,
    _baseline_queries,
    _extract_organization_ids_from_flag,
    _warm_baseline_for_team,
    get_eager_team_ids,
    warm_eager_baseline_op,
)

# Generic placeholder UUIDs for tests — these never touch customer data and
# the flag conditions in production are opaque organization IDs.
_ORG_UUID_A = "11111111-1111-4111-8111-111111111111"
_ORG_UUID_B = "22222222-2222-4222-8222-222222222222"
_ORG_UUID_C = "33333333-3333-4333-8333-333333333333"


def _make_flag(team: Team, *, groups: list[dict], active: bool = True, deleted: bool = False) -> FeatureFlag:
    return FeatureFlag.objects.create(
        team=team,
        key=EAGER_FLAG_KEY,
        active=active,
        deleted=deleted,
        filters={"groups": groups, "aggregation_group_type_index": 0},
    )


def _org_id_group(org_id: str, *, operator: str | None = "exact") -> dict:
    prop: dict = {"key": "id", "type": "group", "group_type_index": 0, "value": org_id}
    if operator is not None:
        prop["operator"] = operator
    return {"properties": [prop], "rollout_percentage": 100}


class TestExtractOrganizationIdsFromFlag:
    @pytest.mark.parametrize(
        "filters,expected",
        [
            pytest.param(
                {"groups": [_org_id_group(_ORG_UUID_A)]},
                [_ORG_UUID_A],
                id="single_group_single_org",
            ),
            pytest.param(
                {"groups": [_org_id_group(_ORG_UUID_A), _org_id_group(_ORG_UUID_B), _org_id_group(_ORG_UUID_C)]},
                [_ORG_UUID_A, _ORG_UUID_B, _ORG_UUID_C],
                id="multiple_groups_preserved_in_order",
            ),
            pytest.param(
                {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "group",
                                    "group_type_index": 0,
                                    "value": [_ORG_UUID_A, _ORG_UUID_B],
                                    "operator": "exact",
                                }
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
                [_ORG_UUID_A, _ORG_UUID_B],
                id="list_value",
            ),
            pytest.param(
                {"groups": [_org_id_group(_ORG_UUID_A, operator=None)]},
                [_ORG_UUID_A],
                id="missing_operator_defaults_to_exact",
            ),
            pytest.param({}, [], id="empty_filters"),
            pytest.param({"groups": []}, [], id="empty_groups"),
            pytest.param(
                {"groups": [_org_id_group(_ORG_UUID_A, operator="icontains")]},
                [],
                id="ignores_non_exact_operator",
            ),
            pytest.param(
                {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "name",
                                    "type": "group",
                                    "group_type_index": 0,
                                    "value": "x",
                                    "operator": "exact",
                                },
                            ]
                        }
                    ]
                },
                [],
                id="ignores_non_id_key",
            ),
            pytest.param(
                {
                    "groups": [
                        {
                            "properties": [
                                {"key": "id", "type": "person", "value": _ORG_UUID_A, "operator": "exact"},
                            ]
                        }
                    ]
                },
                [],
                id="ignores_person_type",
            ),
            # Malformed-shape defenses — should return [] not raise.
            pytest.param({"groups": None}, [], id="groups_is_none"),
            pytest.param({"groups": "not-a-list"}, [], id="groups_is_string"),
            pytest.param({"groups": [None]}, [], id="group_is_none"),
            pytest.param({"groups": ["not-a-dict"]}, [], id="group_is_string"),
            pytest.param({"groups": [{"properties": None}]}, [], id="properties_is_none"),
            pytest.param({"groups": [{"properties": "not-a-list"}]}, [], id="properties_is_string"),
            pytest.param({"groups": [{"properties": [None]}]}, [], id="prop_is_none"),
            pytest.param({"groups": [{"properties": ["string"]}]}, [], id="prop_is_string"),
        ],
    )
    def test_extracts_expected_org_ids(self, filters, expected):
        flag = FeatureFlag(filters=filters)
        assert _extract_organization_ids_from_flag(flag) == expected

    def test_handles_completely_none_filters(self):
        flag = FeatureFlag(filters=None)
        assert _extract_organization_ids_from_flag(flag) == []


@patch("products.web_analytics.dags.eager_web_analytics_precompute.is_cloud", return_value=True)
class TestGetEagerTeamIds(APIBaseTest):
    """The flag is anchored to a fixed team id (EAGER_FLAG_TEAM_ID) in
    production. In tests we patch that constant to point at the test team
    so we can exercise the resolver end-to-end against the test DB.
    `is_cloud` is patched to True at the class level — the production gate
    refuses to resolve on self-hosted instances."""

    def setUp(self):
        super().setUp()
        self.patcher = patch(
            "products.web_analytics.dags.eager_web_analytics_precompute.EAGER_FLAG_TEAM_ID",
            self.team.pk,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _make_org_with_team(self, *, name: str = "Org") -> tuple[Team, str]:
        """Create an org + team. Returns (team, str(org.id))."""
        org = Organization.objects.create(name=name)
        team = Team.objects.create(organization=org, name=f"{name}-team")
        return team, str(org.id)

    def test_returns_empty_when_flag_absent(self, _is_cloud):
        assert get_eager_team_ids() == []

    def test_returns_empty_when_flag_inactive(self, _is_cloud):
        _, org_id = self._make_org_with_team()
        _make_flag(self.team, groups=[_org_id_group(org_id)], active=False)
        assert get_eager_team_ids() == []

    def test_returns_empty_when_flag_deleted(self, _is_cloud):
        _, org_id = self._make_org_with_team()
        _make_flag(self.team, groups=[_org_id_group(org_id)], deleted=True)
        assert get_eager_team_ids() == []

    def test_returns_empty_when_no_org_id_conditions(self, _is_cloud):
        _make_flag(self.team, groups=[{"rollout_percentage": 100}])
        assert get_eager_team_ids() == []

    def test_returns_empty_on_self_hosted(self, _is_cloud):
        _is_cloud.return_value = False
        _, org_id = self._make_org_with_team()
        _make_flag(self.team, groups=[_org_id_group(org_id)])
        assert get_eager_team_ids() == []

    def test_resolves_single_org_to_team(self, _is_cloud):
        target, org_id = self._make_org_with_team(name="A")
        self._make_org_with_team(name="Other")
        _make_flag(self.team, groups=[_org_id_group(org_id)])
        assert get_eager_team_ids() == [target.pk]

    def test_unions_teams_across_multiple_org_groups(self, _is_cloud):
        a, org_a = self._make_org_with_team(name="A")
        b, org_b = self._make_org_with_team(name="B")
        self._make_org_with_team(name="C")
        _make_flag(self.team, groups=[_org_id_group(org_a), _org_id_group(org_b)])
        assert get_eager_team_ids() == sorted([a.pk, b.pk])

    def test_returns_all_teams_in_an_enrolled_org(self, _is_cloud):
        org = Organization.objects.create(name="Multi")
        team_a = Team.objects.create(organization=org, name="multi-a")
        team_b = Team.objects.create(organization=org, name="multi-b")
        _make_flag(self.team, groups=[_org_id_group(str(org.id))])
        assert get_eager_team_ids() == sorted([team_a.pk, team_b.pk])

    def test_unknown_org_id_resolves_to_empty(self, _is_cloud):
        # A flag listing an org UUID that no longer exists should not
        # crash; the resolver just returns no teams.
        _make_flag(self.team, groups=[_org_id_group(str(uuid4()))])
        assert get_eager_team_ids() == []


class TestBaselineQueries:
    def test_matrix_covers_overview_goals_and_vitals(self):
        kinds = {q["kind"] for q in _baseline_queries()}
        assert "WebOverviewQuery" in kinds
        assert "WebGoalsQuery" in kinds
        assert "WebVitalsPathBreakdownQuery" in kinds

    def test_matrix_covers_every_baseline_breakdown(self):
        queries = _baseline_queries()
        seen_breakdowns = {q["breakdownBy"] for q in queries if q["kind"] == "WebStatsTableQuery"}
        expected = {b.value for b in BASELINE_BREAKDOWNS}
        assert seen_breakdowns == expected

    def test_matrix_uses_single_28_day_window(self):
        queries = _baseline_queries()
        windows_seen = {q["dateRange"]["date_from"] for q in queries}
        assert windows_seen == {f"-{BASELINE_WINDOW_DAYS}d"}

    def test_total_query_count_equals_breakdowns_plus_three(self):
        # WebOverview + WebGoals + WebVitalsPathBreakdown + each WebStats breakdown
        assert len(_baseline_queries()) == 3 + len(BASELINE_BREAKDOWNS)

    def test_every_query_filters_test_accounts(self):
        for q in _baseline_queries():
            assert q["filterTestAccounts"] is True

    def test_every_query_opts_in_to_precompute(self):
        # Required to flip the lazy precompute gate (PerQueryOptInNotSet).
        # Without this every warmer query falls back to legacy/raw compute
        # and the `web_*_preaggregated` tables stay cold.
        for q in _baseline_queries():
            assert q["useWebAnalyticsPrecompute"] is True

    def test_includes_frustration_breakdown(self):
        breakdowns = {q.get("breakdownBy") for q in _baseline_queries()}
        assert WebStatsBreakdown.FRUSTRATION_METRICS.value in breakdowns


@patch("products.web_analytics.dags.eager_web_analytics_precompute.is_cloud", return_value=True)
class TestWarmEagerBaselineOp(APIBaseTest):
    """Integration-shaped tests for the op. Query runners are patched so
    no ClickHouse traffic is needed — we assert orchestration semantics."""

    def setUp(self):
        super().setUp()
        self.patcher = patch(
            "products.web_analytics.dags.eager_web_analytics_precompute.EAGER_FLAG_TEAM_ID",
            self.team.pk,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _enroll_org(self, *, name: str) -> tuple[Team, str]:
        """Create an org + team, return the team and `str(org.id)` so it
        can be added to the flag config."""
        org = Organization.objects.create(name=name)
        return Team.objects.create(organization=org, name=f"{name}-team"), str(org.id)

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_one_team_failure_does_not_poison_other_teams(self, get_runner, tag_queries_mock, _is_cloud):
        t1, org_a = self._enroll_org(name="A")
        t2, org_b = self._enroll_org(name="B")
        _make_flag(self.team, groups=[_org_id_group(org_a), _org_id_group(org_b)])

        ok_runner = Mock()
        ok_runner.run.return_value = None
        bad_runner = Mock()
        bad_runner.run.side_effect = RuntimeError("boom")

        def runner_factory(query, team, limit_context):
            return bad_runner if team.pk == t1.pk else ok_runner

        get_runner.side_effect = runner_factory

        context = dagster.build_op_context()
        result = warm_eager_baseline_op(context)

        per_team = len(_baseline_queries())
        assert result["teams"] == 2
        assert result["warmed"] == per_team  # only t2 succeeds
        assert result["failed"] == per_team  # only t1 fails
        assert result["skipped"] == 0
        assert ok_runner.run.call_count == per_team
        assert bad_runner.run.call_count == per_team

        # Both teams must hit the same matrix.
        called_team_ids = {
            call.kwargs.get("team", call.args[1] if len(call.args) > 1 else None).pk
            for call in get_runner.call_args_list
        }
        assert called_team_ids == {t1.pk, t2.pk}

        # Tagging fires for every query so query_log attribution is intact.
        assert tag_queries_mock.call_count == per_team * 2

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_returns_zeroed_metadata_when_no_teams_enrolled(self, get_runner, _is_cloud):
        # No flag → no teams → no runs.
        context = dagster.build_op_context()
        result = warm_eager_baseline_op(context)
        assert result == {"teams": 0, "warmed": 0, "failed": 0, "skipped": 0}
        get_runner.assert_not_called()

    @patch("products.web_analytics.dags.eager_web_analytics_precompute._MAX_ENROLLED_TEAMS", 1)
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_caps_audience_when_resolved_set_is_too_large(self, get_runner, _is_cloud):
        _, org_a = self._enroll_org(name="A")
        _, org_b = self._enroll_org(name="B")
        _make_flag(self.team, groups=[_org_id_group(org_a), _org_id_group(org_b)])

        context = dagster.build_op_context()
        result = warm_eager_baseline_op(context)

        assert result["teams"] == 2
        assert result["warmed"] == 0
        assert result["failed"] == 0
        assert result["skipped"] == 2
        get_runner.assert_not_called()


class TestWarmBaselineForTeam(APIBaseTest):
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_warms_full_matrix(self, get_runner, tag_queries_mock):
        runner = Mock()
        runner.run.return_value = None
        get_runner.return_value = runner

        warmed, failed = _warm_baseline_for_team(Mock(spec=dagster.OpExecutionContext), self.team)

        per_team = len(_baseline_queries())
        assert warmed == per_team
        assert failed == 0
        assert runner.run.call_count == per_team

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_tag_queries_fires_before_get_query_runner(self, get_runner, tag_queries_mock):
        # Order matters: tag_queries writes to a contextvar; any I/O the
        # runner does at construction time must inherit the warmer's tags.
        call_order: list[str] = []

        def record_tag(**kwargs):
            call_order.append("tag")

        def record_get_runner(**kwargs):
            call_order.append("get_runner")
            return Mock(run=Mock())

        tag_queries_mock.side_effect = record_tag
        get_runner.side_effect = record_get_runner

        _warm_baseline_for_team(Mock(spec=dagster.OpExecutionContext), self.team)

        # For each query in the matrix the order must be tag then get_runner.
        pairs = list(zip(call_order[0::2], call_order[1::2]))
        assert pairs and all(p == ("tag", "get_runner") for p in pairs)
