import os
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

import dagster

from posthog.models import Organization, Team

from products.web_analytics.dags.web_dimensional_precompute import (
    DEFAULT_ROLLOUT_TEAM_IDS,
    PRECOMPUTE_CHUNK_DAYS,
    PRECOMPUTE_WINDOW_DAYS,
    SELECTED_TEAM_IDS_ENV_VAR,
    chunk_ranges,
    ensure_web_dimensional_precompute_op,
    get_selected_team_ids,
    web_dimensional_precompute_job,
)

_IS_CLOUD = "products.web_analytics.dags.web_dimensional_precompute.is_cloud"

# Patch chunking to a single chunk so call counts are deterministic in the op tests.
_SINGLE_CHUNK = "products.web_analytics.dags.web_dimensional_precompute.PRECOMPUTE_CHUNK_DAYS"


class TestChunkRanges:
    def test_splits_newest_first_and_bounds_each_chunk(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 31, tzinfo=UTC)
        chunks = chunk_ranges(start, end, 7)
        # Newest first, each <= 7 days, contiguous, fully covering [start, end].
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
        # An explicit empty value disables the job even on cloud.
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


class TestEnsureWebDimensionalPrecomputeOp(APIBaseTest):
    """Orchestration-shaped tests; the ensure_* functions are patched so no
    ClickHouse traffic is needed."""

    def _make_team(self, name: str) -> Team:
        org = Organization.objects.create(name=name)
        return Team.objects.create(organization=org, name=f"{name}-team")

    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed")
    @patch(_SINGLE_CHUNK, PRECOMPUTE_WINDOW_DAYS)  # one chunk → one ensure call per team/table
    def test_drives_both_tables_for_every_selected_team(self, stats_mock, bounces_mock):
        t1 = self._make_team("A")
        t2 = self._make_team("B")
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{t1.pk},{t2.pk}"}):
            result = ensure_web_dimensional_precompute_op(dagster.build_op_context())

        assert result == {"teams": 2, "failures": 0}
        assert stats_mock.call_count == 2
        assert bounces_mock.call_count == 2
        warmed_teams = {call.args[0].pk for call in stats_mock.call_args_list}
        assert warmed_teams == {t1.pk, t2.pk}
        start, end = stats_mock.call_args_list[0].args[1], stats_mock.call_args_list[0].args[2]
        assert (end - start).days == PRECOMPUTE_WINDOW_DAYS

    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed")
    def test_chunking_issues_multiple_bounded_calls(self, stats_mock, bounces_mock):
        # Chunking bounds each ensure call to <= chunk_days so no single INSERT
        # scans the whole window. Exercised here with a 7-day chunk for clarity.
        t1 = self._make_team("A")
        with patch(_SINGLE_CHUNK, 7), patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{t1.pk}"}):
            ensure_web_dimensional_precompute_op(dagster.build_op_context())
        assert stats_mock.call_count > 1
        assert all((e - s).days <= 7 for _t, s, e in (c.args for c in stats_mock.call_args_list))

    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed")
    @patch(_SINGLE_CHUNK, PRECOMPUTE_WINDOW_DAYS)
    def test_one_team_failure_does_not_poison_others(self, stats_mock, bounces_mock):
        t1 = self._make_team("A")
        t2 = self._make_team("B")

        def stats_side_effect(team, start, end):
            if team.pk == t1.pk:
                raise RuntimeError("boom")

        stats_mock.side_effect = stats_side_effect

        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: f"{t1.pk},{t2.pk}"}):
            result = ensure_web_dimensional_precompute_op(dagster.build_op_context())

        assert result["teams"] == 2
        assert result["failures"] == 1
        assert stats_mock.call_count == 2
        assert bounces_mock.call_count == 2

    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed")
    def test_empty_allowlist_is_a_noop(self, stats_mock, bounces_mock):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: ""}):
            result = ensure_web_dimensional_precompute_op(dagster.build_op_context())
        assert result == {"teams": 0, "failures": 0}
        stats_mock.assert_not_called()
        bounces_mock.assert_not_called()

    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed")
    def test_missing_team_is_skipped(self, stats_mock, bounces_mock):
        # A non-existent team id in the allowlist is logged and skipped, not fatal.
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: "999999999"}):
            result = ensure_web_dimensional_precompute_op(dagster.build_op_context())
        assert result == {"teams": 0, "failures": 0}
        stats_mock.assert_not_called()

    def test_job_has_owner_and_runtime_tags(self):
        tags = web_dimensional_precompute_job.tags
        assert tags["owner"] == "team-web-analytics"
        assert "dagster/max_runtime" in tags
