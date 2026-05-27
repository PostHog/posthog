import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

import dagster

from posthog.schema import WebStatsBreakdown

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.feature_flag import FeatureFlag

from products.web_analytics.dags.eager_web_analytics_precompute import (
    BASELINE_BREAKDOWNS,
    BASELINE_WINDOW_DAYS,
    EAGER_FLAG_KEY,
    _baseline_queries,
    _extract_email_domains_from_flag,
    _warm_baseline_for_team,
    get_eager_team_ids,
    warm_eager_baseline_op,
)


def _make_flag(team: Team, *, groups: list[dict], active: bool = True, deleted: bool = False) -> FeatureFlag:
    return FeatureFlag.objects.create(
        team=team,
        key=EAGER_FLAG_KEY,
        active=active,
        deleted=deleted,
        filters={"groups": groups},
    )


def _email_icontains_group(domain: str) -> dict:
    return {
        "properties": [
            {"key": "email", "type": "person", "value": domain, "operator": "icontains"},
        ],
        "rollout_percentage": 100,
    }


class TestExtractEmailDomainsFromFlag:
    @pytest.mark.parametrize(
        "filters,expected",
        [
            pytest.param(
                {"groups": [_email_icontains_group("@lovable.dev")]},
                ["@lovable.dev"],
                id="single_group_string_value",
            ),
            pytest.param(
                {
                    "groups": [
                        _email_icontains_group("@lovable.dev"),
                        _email_icontains_group("@heygen.com"),
                        _email_icontains_group("@researchgate.net"),
                    ]
                },
                ["@lovable.dev", "@heygen.com", "@researchgate.net"],
                id="multiple_groups_preserved_in_order",
            ),
            pytest.param(
                {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["@lovable.dev", "@heygen.com"],
                                    "operator": "icontains",
                                }
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
                ["@lovable.dev", "@heygen.com"],
                id="list_value",
            ),
            pytest.param({}, [], id="empty_filters"),
            pytest.param({"groups": []}, [], id="empty_groups"),
            pytest.param(
                {
                    "groups": [
                        {
                            "properties": [
                                {"key": "email", "type": "person", "value": "@x.com", "operator": "exact"},
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
                [],
                id="ignores_non_icontains_operator",
            ),
            pytest.param(
                {
                    "groups": [
                        {
                            "properties": [
                                {"key": "name", "type": "person", "value": "alice", "operator": "icontains"},
                            ]
                        }
                    ]
                },
                [],
                id="ignores_non_email_key",
            ),
            pytest.param(
                {
                    "groups": [
                        {
                            "properties": [
                                {"key": "email", "type": "group", "value": "@x.com", "operator": "icontains"},
                            ]
                        }
                    ]
                },
                [],
                id="ignores_non_person_type",
            ),
        ],
    )
    def test_extracts_expected_domains(self, filters, expected):
        flag = FeatureFlag(filters=filters)
        assert _extract_email_domains_from_flag(flag) == expected


class TestGetEagerTeamIds(APIBaseTest):
    """The flag is anchored to a fixed team id (EAGER_FLAG_TEAM_ID) in
    production. In tests we patch that constant to point at the test team
    so we can exercise the resolver end-to-end against the test DB."""

    def setUp(self):
        super().setUp()
        self.patcher = patch(
            "products.web_analytics.dags.eager_web_analytics_precompute.EAGER_FLAG_TEAM_ID",
            self.team.pk,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _make_org_with_member(self, *, email: str, name: str = "Org") -> Team:
        org = Organization.objects.create(name=name)
        user = User.objects.create(email=email, first_name="member", distinct_id=email)
        OrganizationMembership.objects.create(user=user, organization=org, level=1)
        return Team.objects.create(organization=org, name=f"{name}-team")

    def test_returns_empty_when_flag_absent(self):
        assert get_eager_team_ids() == []

    def test_returns_empty_when_flag_inactive(self):
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")], active=False)
        self._make_org_with_member(email="alice@lovable.dev")
        assert get_eager_team_ids() == []

    def test_returns_empty_when_flag_deleted(self):
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")], deleted=True)
        self._make_org_with_member(email="alice@lovable.dev")
        assert get_eager_team_ids() == []

    def test_returns_empty_when_no_domain_conditions(self):
        _make_flag(self.team, groups=[{"rollout_percentage": 100}])
        assert get_eager_team_ids() == []

    def test_resolves_single_domain_to_team(self):
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")])
        target = self._make_org_with_member(email="alice@lovable.dev")
        self._make_org_with_member(email="bob@unrelated.com")
        assert get_eager_team_ids() == [target.pk]

    def test_unions_teams_across_multiple_domain_groups(self):
        _make_flag(
            self.team,
            groups=[
                _email_icontains_group("@lovable.dev"),
                _email_icontains_group("@heygen.com"),
            ],
        )
        a = self._make_org_with_member(email="alice@lovable.dev", name="A")
        b = self._make_org_with_member(email="bob@heygen.com", name="B")
        self._make_org_with_member(email="carol@elsewhere.com", name="C")
        assert get_eager_team_ids() == sorted([a.pk, b.pk])

    def test_dedupes_teams_when_org_has_multiple_matching_members(self):
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")])
        org = Organization.objects.create(name="Multi")
        for email in ("alice@lovable.dev", "bob@lovable.dev"):
            user = User.objects.create(email=email, first_name="m", distinct_id=email)
            OrganizationMembership.objects.create(user=user, organization=org, level=1)
        target = Team.objects.create(organization=org, name="multi-team")
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

    def test_window_is_28_days(self):
        for q in _baseline_queries():
            assert q["dateRange"] == {"date_from": f"-{BASELINE_WINDOW_DAYS}d"}

    def test_filters_test_accounts_by_default(self):
        for q in _baseline_queries():
            assert q["filterTestAccounts"] is True

    def test_includes_frustration_breakdown(self):
        # Frustration is rendered as a regular WebStatsTableQuery tile in the UI.
        breakdowns = {q.get("breakdownBy") for q in _baseline_queries()}
        assert WebStatsBreakdown.FRUSTRATION_METRICS.value in breakdowns


class TestWarmEagerBaselineOp(APIBaseTest):
    """Integration-shaped tests for the op. The query runners are patched so
    no ClickHouse traffic is needed — we assert orchestration semantics."""

    def setUp(self):
        super().setUp()
        self.patcher = patch(
            "products.web_analytics.dags.eager_web_analytics_precompute.EAGER_FLAG_TEAM_ID",
            self.team.pk,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _enroll_team(self, *, name: str, domain: str) -> Team:
        org = Organization.objects.create(name=name)
        user = User.objects.create(email=f"u@{domain}", first_name="u", distinct_id=f"u@{domain}")
        OrganizationMembership.objects.create(user=user, organization=org, level=1)
        return Team.objects.create(organization=org, name=f"{name}-team")

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_one_team_failure_does_not_poison_other_teams(self, get_runner):
        _make_flag(self.team, groups=[_email_icontains_group("@x.com"), _email_icontains_group("@y.com")])
        t1 = self._enroll_team(name="A", domain="x.com")
        t2 = self._enroll_team(name="B", domain="y.com")

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
        assert ok_runner.run.call_count == per_team
        assert bad_runner.run.call_count == per_team

        # Sanity-check both teams are exercised against the same matrix.
        called_team_ids = {
            call.kwargs.get("team", call.args[1] if len(call.args) > 1 else None).pk
            for call in get_runner.call_args_list
        }
        assert called_team_ids == {t1.pk, t2.pk}

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_returns_zeroed_metadata_when_no_teams_enrolled(self, get_runner):
        # No flag → no teams → no runs.
        context = dagster.build_op_context()
        result = warm_eager_baseline_op(context)
        assert result == {"teams": 0, "warmed": 0, "failed": 0}
        get_runner.assert_not_called()


class TestWarmBaselineForTeam(APIBaseTest):
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_warms_full_matrix(self, get_runner):
        runner = Mock()
        runner.run.return_value = None
        get_runner.return_value = runner

        warmed, failed = _warm_baseline_for_team(Mock(spec=dagster.OpExecutionContext), self.team)

        per_team = len(_baseline_queries())
        assert warmed == per_team
        assert failed == 0
        assert runner.run.call_count == per_team
