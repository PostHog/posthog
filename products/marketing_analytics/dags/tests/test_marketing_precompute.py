import os
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import dagster
from parameterized import parameterized

from posthog.schema import MarketingAnalyticsDrillDownLevel

from posthog.dags.common import chunk_ranges
from posthog.models import Organization, Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationTable
from products.marketing_analytics.dags.marketing_precompute import (
    COST_MATERIALIZATION_GRAINS,
    DEFAULT_ROLLOUT_TEAM_IDS,
    PRECOMPUTE_CHUNK_DAYS,
    PRECOMPUTE_WINDOW_DAYS,
    SELECTED_TEAM_IDS_ENV_VAR,
    ensure_marketing_precompute_op,
    get_selected_team_ids,
    marketing_precompute_job,
)

_IS_CLOUD = "products.marketing_analytics.dags.marketing_precompute.is_cloud"
_ENSURE = "products.marketing_analytics.dags.marketing_precompute.ensure_precomputed"
_FF = "products.marketing_analytics.backend.hogql_queries.marketing_analytics_config.feature_enabled_or_false"
_DB = "products.marketing_analytics.dags.marketing_precompute.Database"
_FACTORY = "products.marketing_analytics.dags.marketing_precompute.MarketingSourceFactory"
# Patch chunking to a single chunk so call counts are deterministic in the op tests. Must exceed
# PRECOMPUTE_WINDOW_DAYS + the team's attribution window (default 90) to collapse to one chunk.
_SINGLE_CHUNK = "products.marketing_analytics.dags.marketing_precompute.PRECOMPUTE_CHUNK_DAYS"
_BIG_CHUNK = 100000

# Converts cleanly but is_goal_precomputable() rejects it (schema_map remaps a tracked UTM field, which
# the config-agnostic touchpoints table can't serve), so a team with only this goal warms touchpoints but
# no conversions.
_INELIGIBLE_GOAL = {
    "name": "Remapped",
    "kind": "EventsNode",
    "event": "signup",
    "conversion_goal_id": "goal_remapped",
    "conversion_goal_name": "Remapped",
    "schema_map": {"utm_campaign_name": "custom_campaign"},
    "properties": [],
}
# Fully-specified EventsNode goal that IS precomputable (see ConversionGoalProcessor.is_goal_precomputable).
_PRECOMPUTABLE_GOAL = {
    "name": "Signup",  # required by validate_conversion_goals
    "kind": "EventsNode",
    "event": "signup",
    "conversion_goal_id": "goal_signup",
    "conversion_goal_name": "Signup",
    "math": "total",
    "schema_map": {},
    "properties": [],
}


def _ready_mock() -> MagicMock:
    mock = MagicMock()
    mock.return_value.ready = True
    return mock


def _flag_fn(*, conversion: bool = False, costs: bool = False):
    """Stand-in for feature_enabled_or_false that toggles the two precompute flags independently."""

    def _fn(flag, *args, **kwargs):
        return {
            "marketing-analytics-precomputation": conversion,
            "marketing-analytics-costs-precomputation": costs,
        }.get(flag, False)

    return _fn


def _tables(ensure_mock) -> list[LazyComputationTable]:
    return [call.kwargs["table"] for call in ensure_mock.call_args_list]


class TestChunkRanges:
    def test_splits_newest_first_and_bounds_each_chunk(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 31, tzinfo=UTC)
        chunks = chunk_ranges(start, end, 7)
        assert chunks[0][1] == end
        assert chunks[-1][0] == start
        assert all((c_end - c_start).days <= 7 for c_start, c_end in chunks)
        for newer, older in zip(chunks, chunks[1:]):
            assert older[1] == newer[0]  # contiguous
        assert len(chunks) == 5  # 30 days / 7

    def test_single_chunk_when_window_fits(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 5, tzinfo=UTC)
        assert chunk_ranges(start, end, 90) == [(start, end)]

    def test_default_chunk_is_one_day(self):
        # Conservative default: each INSERT scans a single day to bound CH memory.
        assert PRECOMPUTE_CHUNK_DAYS == 1


class TestGetSelectedTeamIds:
    @parameterized.expand(
        [
            ("comma_separated", "2, 47074 ,55348", [2, 47074, 55348]),
            ("skips_blank_and_invalid", " , abc, 2 ,", [2]),
        ]
    )
    def test_env_override_parses(self, _name, raw, expected):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: raw}):
            assert get_selected_team_ids() == expected

    def test_env_set_empty_disables(self):
        with patch(_IS_CLOUD, return_value=True), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: ""}):
            assert get_selected_team_ids() == []

    @parameterized.expand(
        [
            ("cloud_uses_default_rollout", True, DEFAULT_ROLLOUT_TEAM_IDS),
            ("off_cloud_is_empty", False, []),
        ]
    )
    def test_unset_behavior_depends_on_cloud(self, _name, cloud, expected):
        with patch(_IS_CLOUD, return_value=cloud), patch.dict(os.environ, {}, clear=False):
            os.environ.pop(SELECTED_TEAM_IDS_ENV_VAR, None)
            assert get_selected_team_ids() == expected


class TestConversionWarming(APIBaseTest):
    """Touchpoints + conversions orchestration; ensure_precomputed is patched so no ClickHouse traffic."""

    def _make_team(self, name: str, *, goals: list | None = None) -> Team:
        org = Organization.objects.create(name=name)
        team = Team.objects.create(organization=org, name=f"{name}-team")
        if goals is not None:
            team.marketing_analytics_config.conversion_goals = goals
            team.marketing_analytics_config.save()
        return team

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_conversion_flag_off_skips_everything(self, ensure_mock):
        team = self._make_team("A", goals=[_PRECOMPUTABLE_GOAL])
        with (
            patch(_FF, _flag_fn(conversion=False, costs=False)),
            patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}),
        ):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result == {"teams": 1, "conversion_teams": 0, "costs_teams": 0, "failures": 0}
        ensure_mock.assert_not_called()

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_warms_touchpoints_but_no_conversions_for_ineligible_goal(self, ensure_mock):
        # _INELIGIBLE_GOAL remaps a tracked UTM field → not precomputable. Touchpoints (config-agnostic) still warms.
        team = self._make_team("A", goals=[_INELIGIBLE_GOAL])
        with patch(_FF, _flag_fn(conversion=True)), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result["conversion_teams"] == 1
        assert _tables(ensure_mock) == [LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED]

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_warms_conversions_for_precomputable_goal(self, ensure_mock):
        team = self._make_team("A", goals=[_PRECOMPUTABLE_GOAL])
        with patch(_FF, _flag_fn(conversion=True)), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            ensure_marketing_precompute_op(dagster.build_op_context())
        tables = _tables(ensure_mock)
        assert LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED in tables
        assert LazyComputationTable.MARKETING_CONVERSIONS_PREAGGREGATED in tables

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_only_precomputable_goals_warm_conversions(self, ensure_mock):
        # One eligible + one ineligible goal → exactly one conversions job.
        team = self._make_team("A", goals=[_PRECOMPUTABLE_GOAL, _INELIGIBLE_GOAL])
        with patch(_FF, _flag_fn(conversion=True)), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            ensure_marketing_precompute_op(dagster.build_op_context())
        conversion_calls = [
            t for t in _tables(ensure_mock) if t == LazyComputationTable.MARKETING_CONVERSIONS_PREAGGREGATED
        ]
        assert len(conversion_calls) == 1

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_skips_team_without_conversion_goals(self, ensure_mock):
        team = self._make_team("A", goals=None)
        with patch(_FF, _flag_fn(conversion=True)), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result == {"teams": 1, "conversion_teams": 0, "costs_teams": 0, "failures": 0}
        ensure_mock.assert_not_called()

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_touchpoints_window_reaches_back_past_attribution_window(self, ensure_mock):
        team = self._make_team("A", goals=[_INELIGIBLE_GOAL])
        expected = PRECOMPUTE_WINDOW_DAYS + team.marketing_analytics_config.attribution_window_days
        with patch(_FF, _flag_fn(conversion=True)), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            ensure_marketing_precompute_op(dagster.build_op_context())
        kwargs = ensure_mock.call_args_list[0].kwargs  # touchpoints is warmed first
        assert (kwargs["time_range_end"] - kwargs["time_range_start"]).days == expected

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_conversions_window_has_no_attribution_backfill(self, ensure_mock):
        # Conversions span only the query window — the conversion event must fall in-range.
        team = self._make_team("A", goals=[_PRECOMPUTABLE_GOAL])
        with patch(_FF, _flag_fn(conversion=True)), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            ensure_marketing_precompute_op(dagster.build_op_context())
        conv_call = next(
            c
            for c in ensure_mock.call_args_list
            if c.kwargs["table"] == LazyComputationTable.MARKETING_CONVERSIONS_PREAGGREGATED
        )
        assert (
            conv_call.kwargs["time_range_end"] - conv_call.kwargs["time_range_start"]
        ).days == PRECOMPUTE_WINDOW_DAYS

    @patch(_ENSURE, new_callable=_ready_mock)
    def test_chunking_issues_multiple_bounded_calls(self, ensure_mock):
        team = self._make_team("A", goals=[_INELIGIBLE_GOAL])
        with (
            patch(_SINGLE_CHUNK, 7),
            patch(_FF, _flag_fn(conversion=True)),
            patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}),
        ):
            ensure_marketing_precompute_op(dagster.build_op_context())
        assert ensure_mock.call_count > 1
        for call in ensure_mock.call_args_list:
            assert (call.kwargs["time_range_end"] - call.kwargs["time_range_start"]).days <= 7

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_one_team_failure_does_not_poison_others(self, ensure_mock):
        t1 = self._make_team("A", goals=[_INELIGIBLE_GOAL])
        t2 = self._make_team("B", goals=[_INELIGIBLE_GOAL])

        def side_effect(*args, **kwargs):
            if kwargs["team"].pk == t1.pk:
                raise RuntimeError("boom")
            return MagicMock(ready=True)

        ensure_mock.side_effect = side_effect
        with (
            patch(_FF, _flag_fn(conversion=True)),
            patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{t1.pk},{t2.pk}"}),
        ):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result["teams"] == 2
        assert result["failures"] == 1
        assert ensure_mock.call_count == 2

    @patch(_ENSURE)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_not_ready_counts_as_failure(self, ensure_mock):
        ensure_mock.return_value = MagicMock(ready=False, errors=["still pending"])
        team = self._make_team("A", goals=[_INELIGIBLE_GOAL])
        with patch(_FF, _flag_fn(conversion=True)), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result["failures"] == 1

    @patch(_ENSURE, new_callable=_ready_mock)
    def test_empty_allowlist_is_a_noop(self, ensure_mock):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: ""}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result == {"teams": 0, "conversion_teams": 0, "costs_teams": 0, "failures": 0}
        ensure_mock.assert_not_called()

    @patch(_ENSURE, new_callable=_ready_mock)
    def test_missing_team_is_skipped(self, ensure_mock):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: "999999999"}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result == {"teams": 0, "conversion_teams": 0, "costs_teams": 0, "failures": 0}
        ensure_mock.assert_not_called()

    def test_job_has_owner_and_runtime_tags(self):
        tags = marketing_precompute_job.tags
        assert tags["owner"] == "team-web-analytics"
        assert "dagster/max_runtime" in tags


class TestCostsWarming(APIBaseTest):
    """Costs orchestration; the source factory + database are patched so no warehouse/CH access is needed."""

    def _make_team(self, name: str) -> Team:
        org = Organization.objects.create(name=name)
        return Team.objects.create(organization=org, name=f"{name}-team")

    def _fake_adapter(self, *, materializable: bool = True) -> MagicMock:
        adapter = MagicMock()
        adapter.get_source_id.return_value = "src1"
        adapter.supports_level.return_value = True
        adapter.build_materialization_query.return_value = MagicMock() if materializable else None
        return adapter

    def _fake_factory(self, adapters: list) -> MagicMock:
        factory = MagicMock()
        factory.create_adapters.return_value = adapters
        factory.get_valid_adapters.side_effect = lambda a: a
        return factory

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    @patch(_DB)
    def test_costs_flag_off_skips_costs(self, _db, ensure_mock):
        team = self._make_team("A")
        with patch(_FF, _flag_fn(costs=False)), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result == {"teams": 1, "conversion_teams": 0, "costs_teams": 0, "failures": 0}
        ensure_mock.assert_not_called()

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    @patch(_DB)
    def test_warms_costs_per_source_at_every_grain(self, _db, ensure_mock):
        # One source materializable at all 3 grains → one costs job per grain, independent of conversion goals.
        team = self._make_team("A")
        with (
            patch(_FF, _flag_fn(costs=True)),
            patch(_FACTORY, return_value=self._fake_factory([self._fake_adapter()])),
            patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}),
        ):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result["costs_teams"] == 1
        tables = _tables(ensure_mock)
        assert tables == [LazyComputationTable.MARKETING_COSTS_PREAGGREGATED] * len(COST_MATERIALIZATION_GRAINS)

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    @patch(_DB)
    def test_unmaterializable_source_is_skipped(self, _db, ensure_mock):
        team = self._make_team("A")
        with (
            patch(_FF, _flag_fn(costs=True)),
            patch(_FACTORY, return_value=self._fake_factory([self._fake_adapter(materializable=False)])),
            patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}),
        ):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result["costs_teams"] == 0
        ensure_mock.assert_not_called()

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    @patch(_DB)
    def test_costs_database_built_userless_with_access_control_bypassed(self, db_mock, ensure_mock):
        # The safety property: warmer materializes with the same userless, access-bypassed database the
        # read path's INSERT is printed with — so a warmed cost job is identical to the one a read creates.
        team = self._make_team("A")
        with (
            patch(_FF, _flag_fn(costs=True)),
            patch(_FACTORY, return_value=self._fake_factory([self._fake_adapter()])),
            patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}),
        ):
            ensure_marketing_precompute_op(dagster.build_op_context())
        _, kwargs = db_mock.create_for.call_args
        assert kwargs["bypass_warehouse_access_control"] is True
        assert "user" not in kwargs  # no requesting user

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    @patch(_DB)
    def test_costs_filters_sources_by_supported_grain(self, _db, ensure_mock):
        # src_all materializes at every grain; src_campaign only at campaign → 3 + 1 = 4 ensure calls.
        team = self._make_team("A")
        src_all = self._fake_adapter()
        src_all.get_source_id.return_value = "src_all"
        src_campaign = self._fake_adapter()
        src_campaign.get_source_id.return_value = "src_campaign"
        src_campaign.supports_level.side_effect = lambda g: g == MarketingAnalyticsDrillDownLevel.CAMPAIGN
        with (
            patch(_FF, _flag_fn(costs=True)),
            patch(_FACTORY, return_value=self._fake_factory([src_all, src_campaign])),
            patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}),
        ):
            ensure_marketing_precompute_op(dagster.build_op_context())
        assert ensure_mock.call_count == 4

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    @patch(_DB)
    def test_setup_failure_on_one_team_does_not_halt_the_rest(self, db_mock, ensure_mock):
        # A broken warehouse source failing Database.create_for for one team must not abort the op or
        # skip later teams in the allowlist — the failure is counted, the rest still warm.
        broken = self._make_team("A")
        healthy = self._make_team("B")

        def create_for(*, team, **kwargs):
            if team.pk == broken.pk:
                raise RuntimeError("broken warehouse source")
            return MagicMock()

        db_mock.create_for.side_effect = create_for
        with (
            patch(_FF, _flag_fn(costs=True)),
            patch(_FACTORY, return_value=self._fake_factory([self._fake_adapter()])),
            patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{broken.pk},{healthy.pk}"}),
        ):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result["teams"] == 2
        assert result["failures"] == 1  # broken team's costs stage
        assert result["costs_teams"] == 1  # healthy team still warmed
        warmed_teams = {c.kwargs["team"].pk for c in ensure_mock.call_args_list}
        assert warmed_teams == {healthy.pk}
