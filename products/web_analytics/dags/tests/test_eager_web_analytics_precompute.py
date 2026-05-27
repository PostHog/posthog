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
    BASELINE_WINDOWS,
    DASHBOARD_DEFAULT_WINDOW_DAYS,
    EAGER_FLAG_KEY,
    _baseline_queries,
    _extract_email_domains_from_flag,
    _validate_domains,
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
    def test_extracts_expected_domains(self, filters, expected):
        flag = FeatureFlag(filters=filters)
        assert _extract_email_domains_from_flag(flag) == expected

    def test_handles_completely_none_filters(self):
        flag = FeatureFlag(filters=None)
        assert _extract_email_domains_from_flag(flag) == []


class TestValidateDomains:
    @pytest.mark.parametrize(
        "input_domains,expected",
        [
            pytest.param(["@lovable.dev", "@heygen.com"], ["@lovable.dev", "@heygen.com"], id="valid_domains"),
            pytest.param(["lovable.dev"], [], id="rejects_missing_at_prefix"),
            pytest.param(["@a"], [], id="rejects_too_short"),
            pytest.param(["@.com"], ["@.com"], id="accepts_minimum_length"),
            pytest.param(["", "@valid.io"], ["@valid.io"], id="filters_empty_string"),
            pytest.param([".com"], [], id="rejects_typo_dot_com"),
        ],
    )
    def test_validates_domain_shape(self, input_domains, expected):
        assert _validate_domains(input_domains) == expected


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

    def _make_org_with_member(self, *, email: str, name: str = "Org", is_active: bool = True) -> Team:
        org = Organization.objects.create(name=name)
        user = User.objects.create(email=email, first_name="member", distinct_id=email, is_active=is_active)
        OrganizationMembership.objects.create(user=user, organization=org, level=1)
        return Team.objects.create(organization=org, name=f"{name}-team")

    def test_returns_empty_when_flag_absent(self, _is_cloud):
        assert get_eager_team_ids() == []

    def test_returns_empty_when_flag_inactive(self, _is_cloud):
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")], active=False)
        self._make_org_with_member(email="alice@lovable.dev")
        assert get_eager_team_ids() == []

    def test_returns_empty_when_flag_deleted(self, _is_cloud):
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")], deleted=True)
        self._make_org_with_member(email="alice@lovable.dev")
        assert get_eager_team_ids() == []

    def test_returns_empty_when_no_domain_conditions(self, _is_cloud):
        _make_flag(self.team, groups=[{"rollout_percentage": 100}])
        assert get_eager_team_ids() == []

    def test_returns_empty_on_self_hosted(self, _is_cloud):
        _is_cloud.return_value = False
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")])
        self._make_org_with_member(email="alice@lovable.dev")
        assert get_eager_team_ids() == []

    def test_resolves_single_domain_to_team(self, _is_cloud):
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")])
        target = self._make_org_with_member(email="alice@lovable.dev")
        self._make_org_with_member(email="bob@unrelated.com")
        assert get_eager_team_ids() == [target.pk]

    def test_unions_teams_across_multiple_domain_groups(self, _is_cloud):
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

    def test_dedupes_teams_when_org_has_multiple_matching_members(self, _is_cloud):
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")])
        org = Organization.objects.create(name="Multi")
        for email in ("alice@lovable.dev", "bob@lovable.dev"):
            user = User.objects.create(email=email, first_name="m", distinct_id=email)
            OrganizationMembership.objects.create(user=user, organization=org, level=1)
        target = Team.objects.create(organization=org, name="multi-team")
        assert get_eager_team_ids() == [target.pk]

    def test_excludes_orgs_whose_only_matching_member_is_inactive(self, _is_cloud):
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")])
        self._make_org_with_member(email="ghost@lovable.dev", is_active=False)
        assert get_eager_team_ids() == []

    def test_anchors_domain_suffix_so_substring_attacks_do_not_match(self, _is_cloud):
        _make_flag(self.team, groups=[_email_icontains_group("@lovable.dev")])
        # Email contains `@lovable.dev` as a substring but does not end with it.
        # `iregex` (the old impl) would have matched; `iendswith` should not.
        self._make_org_with_member(email="alice@lovable.dev.attacker.example")
        assert get_eager_team_ids() == []

    def test_drops_flag_values_without_at_prefix(self, _is_cloud):
        # A typo where the value is `lovable.dev` (no `@`) is silently
        # ignored — otherwise it would match emails like
        # `lovable.dev-something@x.com`.
        _make_flag(
            self.team,
            groups=[
                {
                    "properties": [
                        {"key": "email", "type": "person", "value": "lovable.dev", "operator": "icontains"},
                    ],
                }
            ],
        )
        self._make_org_with_member(email="alice@lovable.dev")
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

    def test_matrix_warms_both_windows(self):
        queries = _baseline_queries()
        windows_seen = {q["dateRange"]["date_from"] for q in queries}
        assert windows_seen == {f"-{DASHBOARD_DEFAULT_WINDOW_DAYS}d", f"-{BASELINE_WINDOW_DAYS}d"}

    def test_total_query_count_equals_breakdowns_plus_three_per_window(self):
        per_window = 3 + len(BASELINE_BREAKDOWNS)
        assert len(_baseline_queries()) == per_window * len(BASELINE_WINDOWS)

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

    def _enroll_team(self, *, name: str, domain: str) -> Team:
        # Use `name` as the local-part so multiple enrolled teams sharing the
        # same domain don't collide on `posthog_user.distinct_id`.
        org = Organization.objects.create(name=name)
        email = f"{name.lower()}@{domain}"
        user = User.objects.create(email=email, first_name=name, distinct_id=email)
        OrganizationMembership.objects.create(user=user, organization=org, level=1)
        return Team.objects.create(organization=org, name=f"{name}-team")

    @patch("products.web_analytics.dags.eager_web_analytics_precompute.tag_queries")
    @patch("products.web_analytics.dags.eager_web_analytics_precompute.get_query_runner")
    def test_one_team_failure_does_not_poison_other_teams(self, get_runner, tag_queries_mock, _is_cloud):
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
        _make_flag(self.team, groups=[_email_icontains_group("@x.com")])
        self._enroll_team(name="A", domain="x.com")
        self._enroll_team(name="B", domain="x.com")

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
        tag_queries_mock.side_effect = lambda **kwargs: call_order.append("tag")
        get_runner.side_effect = lambda **kwargs: call_order.append("get_runner") or Mock(run=Mock())

        _warm_baseline_for_team(Mock(spec=dagster.OpExecutionContext), self.team)

        # For each query in the matrix the order must be tag then get_runner.
        pairs = list(zip(call_order[0::2], call_order[1::2]))
        assert pairs and all(p == ("tag", "get_runner") for p in pairs)
