import os
from collections.abc import Callable
from datetime import UTC, datetime

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import dagster
from parameterized import parameterized

from posthog.schema import DateRange, IntervalType

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.marketing_analytics.dags.marketing_sessions_precompute import (
    _ensure_for_team,
    ensure_marketing_sessions_precompute_op,
    get_selected_team_ids,
)

_ENSURE = "products.marketing_analytics.dags.marketing_sessions_precompute.ensure_marketing_sessions_precomputed"

START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 2, tzinfo=UTC)


class TestMarketingSessionsPrecomputeDag(APIBaseTest):
    @parameterized.expand([(None, []), ("", []), ("12, 34", [12, 34])])
    def test_rollout_requires_an_explicit_allowlist(self, value: str | None, expected: list[int]) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MARKETING_SESSIONS_PRECOMPUTE_TEAM_IDS", None)
            if value is not None:
                os.environ["MARKETING_SESSIONS_PRECOMPUTE_TEAM_IDS"] = value
            assert get_selected_team_ids() == expected

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

    @parameterized.expand(
        [
            ("default", "UTC", "2024-07-05T12:00:00Z", 90, "2024-01-06T00:00:00Z"),
            ("short", "UTC", "2024-07-05T12:00:00Z", 7, "2024-03-29T00:00:00Z"),
            ("west_before_midnight", "America/Los_Angeles", "2024-07-05T02:00:00Z", 30, "2024-03-05T07:00:00Z"),
            ("west_after_midnight", "America/Los_Angeles", "2024-07-05T12:00:00Z", 30, "2024-03-06T07:00:00Z"),
            ("east", "Pacific/Auckland", "2024-07-05T16:00:00Z", 30, "2024-03-06T11:00:00Z"),
            ("spring", "America/Los_Angeles", "2024-03-15T18:00:00Z", 30, "2023-11-15T08:00:00Z"),
            ("fall", "America/Los_Angeles", "2024-11-15T18:00:00Z", 30, "2024-07-17T07:00:00Z"),
            ("spring_day", "America/Los_Angeles", "2024-03-10T09:00:00Z", 30, "2023-11-10T08:00:00Z"),
            ("fall_day", "America/Los_Angeles", "2024-11-03T08:00:00Z", 30, "2024-07-05T07:00:00Z"),
        ]
    )
    def test_warmer_covers_display_plus_team_lookback_and_reachback(
        self, _name: str, timezone: str, now: str, lookback: int, expected_start: str
    ) -> None:
        self.team.timezone = timezone
        self.team.save(update_fields=["timezone"])
        config = self.team.marketing_analytics_config
        config.attribution_window_days = lookback
        config.save()
        module = "products.marketing_analytics.dags.marketing_sessions_precompute"
        with (
            time_machine.travel(now, tick=False),
            patch(f"{module}.get_selected_team_ids", return_value=[self.team.pk]),
            patch(
                "products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute.PRECOMPUTE_WINDOW_DAYS",
                90,
            ),
            patch(f"{module}._ensure_for_team", return_value=0) as ensure,
        ):
            with dagster.build_op_context() as context:
                assert ensure_marketing_sessions_precompute_op(context) == {"teams": 1, "failures": 0}
        args = ensure.call_args.args
        assert args[2] == datetime.fromisoformat(expected_start)
        date_range = QueryDateRange(
            DateRange(date_from="-90d"), self.team, IntervalType.DAY, datetime.fromisoformat(now)
        )
        assert args[3] == date_range.date_to().astimezone(UTC)
