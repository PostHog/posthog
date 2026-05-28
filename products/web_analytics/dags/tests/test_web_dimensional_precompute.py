from posthog.test.base import APIBaseTest
from unittest.mock import patch

import dagster

from posthog.models import Organization, Team

from products.web_analytics.dags.web_dimensional_precompute import (
    PRECOMPUTE_WINDOW_DAYS,
    ensure_web_dimensional_precompute_op,
    web_dimensional_precompute_job,
)


class TestEnsureWebDimensionalPrecomputeOp(APIBaseTest):
    """Orchestration-shaped tests; the ensure_* functions are patched so no
    ClickHouse traffic is needed."""

    def _make_team(self, name: str) -> Team:
        org = Organization.objects.create(name=name)
        return Team.objects.create(organization=org, name=f"{name}-team")

    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.get_team_ids_from_sources")
    def test_drives_both_tables_for_every_team(self, team_ids_mock, stats_mock, bounces_mock):
        t1 = self._make_team("A")
        t2 = self._make_team("B")
        team_ids_mock.return_value = [t1.pk, t2.pk]

        context = dagster.build_op_context()
        result = ensure_web_dimensional_precompute_op(context)

        assert result == {"teams": 2, "failures": 0}
        assert stats_mock.call_count == 2
        assert bounces_mock.call_count == 2

        # Every call covers the rolling window for the right team.
        warmed_teams = {call.args[0].pk for call in stats_mock.call_args_list}
        assert warmed_teams == {t1.pk, t2.pk}
        start, end = stats_mock.call_args_list[0].args[1], stats_mock.call_args_list[0].args[2]
        assert (end - start).days == PRECOMPUTE_WINDOW_DAYS

    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.get_team_ids_from_sources")
    def test_one_team_failure_does_not_poison_others(self, team_ids_mock, stats_mock, bounces_mock):
        t1 = self._make_team("A")
        t2 = self._make_team("B")
        team_ids_mock.return_value = [t1.pk, t2.pk]

        def stats_side_effect(team, start, end):
            if team.pk == t1.pk:
                raise RuntimeError("boom")

        stats_mock.side_effect = stats_side_effect

        context = dagster.build_op_context()
        result = ensure_web_dimensional_precompute_op(context)

        assert result["teams"] == 2
        # t1's stats raised; bounces still attempted for both, stats attempted for both.
        assert result["failures"] == 1
        assert stats_mock.call_count == 2
        assert bounces_mock.call_count == 2

    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_bounces_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.ensure_web_stats_dimensional_precomputed")
    @patch("products.web_analytics.dags.web_dimensional_precompute.get_team_ids_from_sources")
    def test_no_teams_is_a_noop(self, team_ids_mock, stats_mock, bounces_mock):
        team_ids_mock.return_value = []
        context = dagster.build_op_context()
        result = ensure_web_dimensional_precompute_op(context)
        assert result == {"teams": 0, "failures": 0}
        stats_mock.assert_not_called()
        bounces_mock.assert_not_called()

    def test_job_has_owner_and_runtime_tags(self):
        tags = web_dimensional_precompute_job.tags
        assert tags["owner"] == "team-web-analytics"
        assert "dagster/max_runtime" in tags
