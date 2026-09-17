from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import dagster
from parameterized import parameterized

from posthog.models import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.marketing_analytics.dags.marketing_sessions_precompute import (
    _ensure_for_team,
    ensure_marketing_sessions_precompute_op,
)

_ENSURE = "products.marketing_analytics.dags.marketing_sessions_precompute.ensure_marketing_sessions_precomputed"

START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 2, tzinfo=UTC)


class TestMarketingSessionsPrecomputeDag(APIBaseTest):
    def _run(self, side_effect: Callable[[Team, datetime, datetime], LazyComputationResult] | Exception) -> int:
        with patch(_ENSURE, side_effect=side_effect):
            return _ensure_for_team(MagicMock(), self.team, START, END, chunk_days=1)

    def test_a_chunk_the_executor_reports_as_not_ready_counts_as_a_failure(self) -> None:
        # The executor signals a failed insert through the result, not by raising. Counting that
        # chunk as done leaves a window unmaterialized while the DAG reports a clean run.
        result = LazyComputationResult(ready=False, job_ids=[], errors=["insert failed"])
        assert self._run(lambda *args, **kwargs: result) == 1

    def test_a_ready_chunk_counts_as_a_success(self) -> None:
        result = LazyComputationResult(ready=True, job_ids=[])
        assert self._run(lambda *args, **kwargs: result) == 0

    def test_a_raising_chunk_still_counts_as_a_failure(self) -> None:
        assert self._run(RuntimeError("boom")) == 1

    @parameterized.expand([("default", 90, 181), ("short", 7, 98)])
    def test_warmer_covers_display_plus_team_lookback_and_reachback(self, _name: str, lookback: int, span: int) -> None:
        config = self.team.marketing_analytics_config
        config.attribution_window_days = lookback
        config.save()
        module = "products.marketing_analytics.dags.marketing_sessions_precompute"
        with (
            patch(f"{module}.get_selected_team_ids", return_value=[self.team.pk]),
            patch(f"{module}.PRECOMPUTE_WINDOW_DAYS", 90),
            patch(
                "products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute.PRECOMPUTE_WINDOW_DAYS",
                90,
            ),
            patch(f"{module}._ensure_for_team", return_value=0) as ensure,
        ):
            with dagster.build_op_context() as context:
                assert ensure_marketing_sessions_precompute_op(context) == {"teams": 1, "failures": 0}
        args = ensure.call_args.args
        assert args[3] - args[2] == timedelta(days=span)
