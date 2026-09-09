from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.marketing_analytics.dags.marketing_sessions_precompute import _ensure_for_team

_ENSURE = "products.marketing_analytics.dags.marketing_sessions_precompute.ensure_marketing_sessions_precomputed"

START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 2, tzinfo=UTC)


class TestMarketingSessionsPrecomputeDag(APIBaseTest):
    def _run(self, side_effect) -> int:
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
