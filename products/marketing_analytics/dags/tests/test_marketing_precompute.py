import os
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import dagster

from posthog.models import Organization, Team

from products.marketing_analytics.dags.marketing_precompute import (
    DEFAULT_ROLLOUT_TEAM_IDS,
    PRECOMPUTE_CHUNK_DAYS,
    PRECOMPUTE_WINDOW_DAYS,
    SELECTED_TEAM_IDS_ENV_VAR,
    chunk_ranges,
    ensure_marketing_precompute_op,
    get_selected_team_ids,
    marketing_precompute_job,
)

_IS_CLOUD = "products.marketing_analytics.dags.marketing_precompute.is_cloud"
_ENSURE = "products.marketing_analytics.dags.marketing_precompute.ensure_precomputed"
# Patch chunking to a single chunk so call counts are deterministic in the op tests. Must exceed
# PRECOMPUTE_WINDOW_DAYS + the team's attribution window (default 90) to collapse to one chunk.
_SINGLE_CHUNK = "products.marketing_analytics.dags.marketing_precompute.PRECOMPUTE_CHUNK_DAYS"
_BIG_CHUNK = 100000

# Minimal valid conversion goal — only needs to pass validate_conversion_goals so the team is
# treated as having goals. The warming path is goal-agnostic (shared touchpoints table).
_GOAL = {"name": "Signup", "kind": "EventsNode", "schema_map": {}}


def _ready_mock() -> MagicMock:
    mock = MagicMock()
    mock.return_value.ready = True
    return mock


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
    def test_env_override_parses_comma_separated_ids(self):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: "2, 47074 ,55348"}):
            assert get_selected_team_ids() == [2, 47074, 55348]

    def test_env_override_skips_blank_and_invalid(self):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: " , abc, 2 ,"}):
            assert get_selected_team_ids() == [2]

    def test_env_set_empty_disables(self):
        with patch(_IS_CLOUD, return_value=True), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: ""}):
            assert get_selected_team_ids() == []

    def test_unset_uses_default_rollout_on_cloud(self):
        with patch(_IS_CLOUD, return_value=True), patch.dict(os.environ, {}, clear=False):
            os.environ.pop(SELECTED_TEAM_IDS_ENV_VAR, None)
            assert get_selected_team_ids() == DEFAULT_ROLLOUT_TEAM_IDS

    def test_unset_is_empty_off_cloud(self):
        with patch(_IS_CLOUD, return_value=False), patch.dict(os.environ, {}, clear=False):
            os.environ.pop(SELECTED_TEAM_IDS_ENV_VAR, None)
            assert get_selected_team_ids() == []


class TestEnsureMarketingPrecomputeOp(APIBaseTest):
    """Orchestration-shaped tests; ensure_precomputed is patched so no ClickHouse traffic is needed."""

    def _make_team(self, name: str, *, with_goal: bool) -> Team:
        org = Organization.objects.create(name=name)
        team = Team.objects.create(organization=org, name=f"{name}-team")
        if with_goal:
            team.marketing_analytics_config.conversion_goals = [_GOAL]
            team.marketing_analytics_config.save()
        return team

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)  # one chunk → one ensure call per team
    def test_warms_every_selected_team_with_goals(self, ensure_mock):
        t1 = self._make_team("A", with_goal=True)
        t2 = self._make_team("B", with_goal=True)
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{t1.pk},{t2.pk}"}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())

        assert result == {"teams": 2, "skipped": 0, "failures": 0}
        assert ensure_mock.call_count == 2
        warmed_teams = {call.kwargs["team"].pk for call in ensure_mock.call_args_list}
        assert warmed_teams == {t1.pk, t2.pk}

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_skips_team_without_conversion_goals(self, ensure_mock):
        with_goal = self._make_team("A", with_goal=True)
        without_goal = self._make_team("B", with_goal=False)
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{with_goal.pk},{without_goal.pk}"}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())

        assert result == {"teams": 1, "skipped": 1, "failures": 0}
        assert ensure_mock.call_count == 1
        assert ensure_mock.call_args_list[0].kwargs["team"].pk == with_goal.pk

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_window_reaches_back_past_attribution_window(self, ensure_mock):
        # The warmed window covers PRECOMPUTE_WINDOW_DAYS of lookback plus the team's attribution
        # window, so a read's [date_from - attribution_window, date_to] is fully served.
        team = self._make_team("A", with_goal=True)
        expected_days = PRECOMPUTE_WINDOW_DAYS + team.marketing_analytics_config.attribution_window_days
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            ensure_marketing_precompute_op(dagster.build_op_context())

        kwargs = ensure_mock.call_args_list[0].kwargs
        assert (kwargs["time_range_end"] - kwargs["time_range_start"]).days == expected_days

    @patch(_ENSURE, new_callable=_ready_mock)
    def test_chunking_issues_multiple_bounded_calls(self, ensure_mock):
        # Chunking bounds each ensure call to <= chunk_days so no single INSERT scans the whole window.
        team = self._make_team("A", with_goal=True)
        with patch(_SINGLE_CHUNK, 7), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            ensure_marketing_precompute_op(dagster.build_op_context())
        assert ensure_mock.call_count > 1
        for call in ensure_mock.call_args_list:
            span = call.kwargs["time_range_end"] - call.kwargs["time_range_start"]
            assert span.days <= 7

    @patch(_ENSURE, new_callable=_ready_mock)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_one_team_failure_does_not_poison_others(self, ensure_mock):
        t1 = self._make_team("A", with_goal=True)
        t2 = self._make_team("B", with_goal=True)

        def side_effect(*args, **kwargs):
            if kwargs["team"].pk == t1.pk:
                raise RuntimeError("boom")
            return MagicMock(ready=True)

        ensure_mock.side_effect = side_effect

        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{t1.pk},{t2.pk}"}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())

        assert result == {"teams": 2, "skipped": 0, "failures": 1}
        assert ensure_mock.call_count == 2

    @patch(_ENSURE)
    @patch(_SINGLE_CHUNK, _BIG_CHUNK)
    def test_not_ready_counts_as_failure(self, ensure_mock):
        ensure_mock.return_value = MagicMock(ready=False, errors=["still pending"])
        team = self._make_team("A", with_goal=True)
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{team.pk}"}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result == {"teams": 1, "skipped": 0, "failures": 1}

    @patch(_ENSURE, new_callable=_ready_mock)
    def test_empty_allowlist_is_a_noop(self, ensure_mock):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: ""}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result == {"teams": 0, "skipped": 0, "failures": 0}
        ensure_mock.assert_not_called()

    @patch(_ENSURE, new_callable=_ready_mock)
    def test_missing_team_is_skipped(self, ensure_mock):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: "999999999"}):
            result = ensure_marketing_precompute_op(dagster.build_op_context())
        assert result == {"teams": 0, "skipped": 0, "failures": 0}
        ensure_mock.assert_not_called()

    def test_job_has_owner_and_runtime_tags(self):
        tags = marketing_precompute_job.tags
        assert tags["owner"] == "team-web-analytics"
        assert "dagster/max_runtime" in tags
