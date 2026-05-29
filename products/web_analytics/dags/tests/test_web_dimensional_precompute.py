import os

from posthog.test.base import APIBaseTest
from unittest.mock import patch

import dagster

from posthog.models import Organization, Team

from products.web_analytics.dags.web_dimensional_precompute import (
    PRECOMPUTE_WINDOW_DAYS,
    SELECTED_TEAM_IDS_ENV_VAR,
    ensure_web_dimensional_precompute_op,
    get_selected_team_ids,
    web_dimensional_precompute_job,
)


class TestGetSelectedTeamIds:
    def test_parses_comma_separated_ids(self):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: "2, 47074 ,55348"}):
            assert get_selected_team_ids() == [2, 47074, 55348]

    def test_empty_or_invalid_entries_skipped(self):
        with patch.dict(os.environ, {SELECTED_TEAM_IDS_ENV_VAR: " , abc, 2 ,"}):
            assert get_selected_team_ids() == [2]

    def test_unset_is_empty(self):
        with patch.dict(os.environ, {}, clear=False):
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
