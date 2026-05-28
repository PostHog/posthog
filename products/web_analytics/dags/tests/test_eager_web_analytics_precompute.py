from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

import dagster

from posthog.schema import WebStatsBreakdown

from posthog.models import Organization, Team

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


def _flag(*, groups: list[dict], active: bool = True, deleted: bool = False) -> dict:
    """Build a flag-definition dict matching the SDK's local-evaluation shape."""
    return {
        "key": EAGER_FLAG_KEY,
        "active": active,
        "deleted": deleted,
        "filters": {"groups": groups, "aggregation_group_type_index": 0},
    }


def _org_id_group(org_id: str, *, operator: str | None = "exact") -> dict:
    prop: dict = {"key": "id", "type": "group", "group_type_index": 0, "value": org_id}
    if operator is not None:
        prop["operator"] = operator
    return {"properties": [prop], "rollout_percentage": 100}


class TestExtractOrganizationIdsFromFlag:
    @pytest.mark.parametrize(
        "flag,expected",
        [
            pytest.param(
                _flag(groups=[_org_id_group(_ORG_UUID_A)]),
                [_ORG_UUID_A],
                id="single_group_single_org",
            ),
            pytest.param(
                _flag(groups=[_org_id_group(_ORG_UUID_A), _org_id_group(_ORG_UUID_B), _org_id_group(_ORG_UUID_C)]),
                [_ORG_UUID_A, _ORG_UUID_B, _ORG_UUID_C],
                id="multiple_groups_preserved_in_order",
            ),
            pytest.param(
                {
                    "filters": {
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
                    }
                },
                [_ORG_UUID_A, _ORG_UUID_B],
                id="list_value",
            ),
            pytest.param(
                _flag(groups=[_org_id_group(_ORG_UUID_A, operator=None)]),
                [_ORG_UUID_A],
                id="missing_operator_defaults_to_exact",
            ),
            pytest.param({"filters": {}}, [], id="empty_filters"),
            pytest.param({"filters": {"groups": []}}, [], id="empty_groups"),
            pytest.param(
                _flag(groups=[_org_id_group(_ORG_UUID_A, operator="icontains")]),
                [],
                id="ignores_non_exact_operator",
            ),
            pytest.param(
                {
                    "filters": {
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
                    }
                },
                [],
                id="ignores_non_id_key",
            ),
            pytest.param(
                {
                    "filters": {
                        "groups": [
                            {
                                "properties": [
                                    {"key": "id", "type": "person", "value": _ORG_UUID_A, "operator": "exact"},
                                ]
                            }
                        ]
                    }
                },
                [],
                id="ignores_person_type",
            ),
            # Malformed-shape defenses — should return [] not raise.
            pytest.param({"filters": {"groups": None}}, [], id="groups_is_none"),
            pytest.param({"filters": {"groups": "not-a-list"}}, [], id="groups_is_string"),
            pytest.param({"filters": {"groups": [None]}}, [], id="group_is_none"),
            pytest.param({"filters": {"groups": ["not-a-dict"]}}, [], id="group_is_string"),
            pytest.param({"filters": {"groups": [{"properties": None}]}}, [], id="properties_is_none"),
            pytest.param({"filters": {"groups": [{"properties": "not-a-list"}]}}, [], id="properties_is_string"),
            pytest.param({"filters": {"groups": [{"properties": [None]}]}}, [], id="prop_is_none"),
            pytest.param({"filters": {"groups": [{"properties": ["string"]}]}}, [], id="prop_is_string"),
            pytest.param({}, [], id="flag_has_no_filters_key"),
            pytest.param({"filters": None}, [], id="filters_is_none"),
        ],
    )
    def test_extracts_expected_org_ids(self, flag, expected):
        assert _extract_organization_ids_from_flag(flag) == expected

    def test_handles_completely_none_flag(self):
        assert _extract_organization_ids_from_flag(None) == []  # type: ignore[arg-type]


@patch("products.web_analytics.dags.eager_web_analytics_precompute.is_cloud", return_value=True)
@patch("products.web_analytics.dags.eager_web_analytics_precompute.posthoganalytics.feature_flag_definitions")
class TestGetEagerTeamIds(APIBaseTest):
    """The flag definition is read from the posthoganalytics SDK's local
    evaluation cache. Tests patch the SDK accessor to return a stubbed
    definitions list; `is_cloud` is forced True so the prod gate doesn't
    refuse to resolve."""

    def _make_org_with_team(self, *, name: str = "Org") -> tuple[Team, str]:
        org = Organization.objects.create(name=name)
        team = Team.objects.create(organization=org, name=f"{name}-team")
        return team, str(org.id)

    def test_returns_empty_when_flag_absent(self, defs, _is_cloud):
        defs.return_value = []
        assert get_eager_team_ids() == []

    def test_returns_empty_when_flag_inactive(self, defs, _is_cloud):
        _, org_id = self._make_org_with_team()
        defs.return_value = [_flag(groups=[_org_id_group(org_id)], active=False)]
        assert get_eager_team_ids() == []

    def test_returns_empty_when_flag_deleted(self, defs, _is_cloud):
        _, org_id = self._make_org_with_team()
        defs.return_value = [_flag(groups=[_org_id_group(org_id)], deleted=True)]
        assert get_eager_team_ids() == []

    def test_returns_empty_when_no_org_id_conditions(self, defs, _is_cloud):
        defs.return_value = [_flag(groups=[{"rollout_percentage": 100}])]
        assert get_eager_team_ids() == []

    def test_returns_empty_on_self_hosted(self, defs, _is_cloud):
        _is_cloud.return_value = False
        _, org_id = self._make_org_with_team()
        defs.return_value = [_flag(groups=[_org_id_group(org_id)])]
        assert get_eager_team_ids() == []

    def test_returns_empty_when_sdk_returns_none(self, defs, _is_cloud):
        defs.return_value = None
        assert get_eager_team_ids() == []

    def test_resolves_single_org_to_team(self, defs, _is_cloud):
        target, org_id = self._make_org_with_team(name="A")
        self._make_org_with_team(name="Other")
        defs.return_value = [_flag(groups=[_org_id_group(org_id)])]
        assert get_eager_team_ids() == [target.pk]

    def test_unions_teams_across_multiple_org_groups(self, defs, _is_cloud):
        a, org_a = self._make_org_with_team(name="A")
        b, org_b = self._make_org_with_team(name="B")
        self._make_org_with_team(name="C")
        defs.return_value = [_flag(groups=[_org_id_group(org_a), _org_id_group(org_b)])]
        assert get_eager_team_ids() == sorted([a.pk, b.pk])

    def test_returns_all_teams_in_an_enrolled_org(self, defs, _is_cloud):
        org = Organization.objects.create(name="Multi")
        team_a = Team.objects.create(organization=org, name="multi-a")
        team_b = Team.objects.create(organization=org, name="multi-b")
        defs.return_value = [_flag(groups=[_org_id_group(str(org.id))])]
        assert get_eager_team_ids() == sorted([team_a.pk, team_b.pk])

    def test_unknown_org_id_resolves_to_empty(self, defs, _is_cloud):
        # A flag listing an org UUID that no longer exists should not
        # crash; the resolver just returns no teams.
        defs.return_value = [_flag(groups=[_org_id_group(str(uuid4()))])]
        assert get_eager_team_ids() == []

    def test_ignores_other_flags_in_the_sdk_cache(self, defs, _is_cloud):
        target, org_id = self._make_org_with_team(name="Target")
        defs.return_value = [
            {"key": "some-other-flag", "active": True, "filters": {"groups": [_org_id_group(str(uuid4()))]}},
            _flag(groups=[_org_id_group(org_id)]),
            {"key": "yet-another-flag", "active": True, "filters": {"groups": [_org_id_group(str(uuid4()))]}},
        ]
        assert get_eager_team_ids() == [target.pk]


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

    def test_vitals_query_sets_path_cleaning_for_default_dashboard_hit(self):
        # Without `doPathCleaning=True`, the vitals lazy precompute hashes a
        # different cache key than the dashboard's default request and the
        # warmer's job goes unused.
        vitals = next(q for q in _baseline_queries() if q["kind"] == "WebVitalsPathBreakdownQuery")
        assert vitals["doPathCleaning"] is True

    @pytest.mark.parametrize(
        "breakdown",
        [WebStatsBreakdown.PAGE, WebStatsBreakdown.INITIAL_PAGE],
        ids=lambda b: b.value,
    )
    def test_path_breakdowns_include_bounce_rate(self, breakdown):
        # `web_stats_paths_lazy_precompute` rejects PAGE/INITIAL_PAGE queries
        # unless `includeBounceRate=True` — without it the warmer falls
        # through to raw stats compute and the preagg table stays cold.
        query = next(
            q for q in _baseline_queries() if q["kind"] == "WebStatsTableQuery" and q["breakdownBy"] == breakdown.value
        )
        assert query["includeBounceRate"] is True

    def test_other_breakdowns_do_not_set_include_bounce_rate(self):
        # The bounce-rate flag is only needed for PAGE/INITIAL_PAGE which
        # route through `web_stats_paths_lazy_precompute`. Other breakdowns
        # would route through a different (non-paths) lazy module that
        # doesn't gate on it.
        for q in _baseline_queries():
            if q["kind"] != "WebStatsTableQuery":
                continue
            if q["breakdownBy"] in (WebStatsBreakdown.PAGE.value, WebStatsBreakdown.INITIAL_PAGE.value):
                continue
            assert "includeBounceRate" not in q


@patch("products.web_analytics.dags.eager_web_analytics_precompute.is_cloud", return_value=True)
@patch("products.web_analytics.dags.eager_web_analytics_precompute.posthoganalytics.feature_flag_definitions")
class TestWarmEagerBaselineOp(APIBaseTest):
    """Integration-shaped tests for the op. Query runners are patched so
    no ClickHouse traffic is needed — we assert orchestration semantics."""

    def _enroll_org(self, *, name: str) -> tuple[Team, str]:
        """Create an org + team, return the team and `str(org.id)`."""
        org = Organization.objects.create(name=name)
        return Team.objects.create(organization=org, name=f"{name}-team"), str(org.id)

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_one_team_failure_does_not_poison_other_teams(self, get_runner, tag_queries_mock, defs, _is_cloud):
        t1, org_a = self._enroll_org(name="A")
        t2, org_b = self._enroll_org(name="B")
        defs.return_value = [_flag(groups=[_org_id_group(org_a), _org_id_group(org_b)])]

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
    def test_returns_zeroed_metadata_when_no_teams_enrolled(self, get_runner, defs, _is_cloud):
        # No flag → no teams → no runs.
        defs.return_value = []
        context = dagster.build_op_context()
        result = warm_eager_baseline_op(context)
        assert result == {"teams": 0, "warmed": 0, "failed": 0, "skipped": 0}
        get_runner.assert_not_called()

    @patch("products.web_analytics.dags.eager_web_analytics_precompute._MAX_ENROLLED_TEAMS", 1)
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_caps_audience_when_resolved_set_is_too_large(self, get_runner, defs, _is_cloud):
        _, org_a = self._enroll_org(name="A")
        _, org_b = self._enroll_org(name="B")
        defs.return_value = [_flag(groups=[_org_id_group(org_a), _org_id_group(org_b)])]

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
