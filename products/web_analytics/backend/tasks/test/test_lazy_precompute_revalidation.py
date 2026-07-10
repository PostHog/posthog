from posthog.test.base import BaseTest
from unittest import mock

from posthog.schema import DateRange, WebOverviewQuery

from posthog.clickhouse.query_tagging import get_query_tag_value, reset_query_tags
from posthog.hogql_queries.query_runner import ExecutionMode

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import REVALIDATION_TRIGGER
from products.web_analytics.backend.tasks.lazy_precompute_revalidation import revalidate_web_analytics_precompute

_MOD = "products.web_analytics.backend.tasks.lazy_precompute_revalidation"


class TestRevalidateWebAnalyticsPrecompute(BaseTest):
    def tearDown(self):
        # In production Celery resets query tags on task_postrun; calling the task
        # function directly leaves them on the contextvar.
        reset_query_tags()
        super().tearDown()

    def test_reruns_query_as_background_trigger_with_forced_recompute(self):
        payload = WebOverviewQuery(dateRange=DateRange(date_from="-7d"), properties=[]).model_dump(
            mode="json", exclude_none=True
        )
        seen: dict = {}

        def fake_get_query_runner(*, query, team, limit_context):
            # The trigger tag must be set BEFORE runner construction, or the ensure
            # inside the run would not see a background trigger and would be served
            # stale itself instead of recomputing.
            seen["trigger_at_construction"] = get_query_tag_value("trigger")
            seen["team"] = team
            seen["query"] = query
            seen["runner"] = mock.Mock()
            return seen["runner"]

        with mock.patch(f"{_MOD}.get_query_runner", side_effect=fake_get_query_runner):
            revalidate_web_analytics_precompute(team_id=self.team.pk, query=payload)

        assert seen["trigger_at_construction"] == REVALIDATION_TRIGGER
        assert seen["team"].pk == self.team.pk
        assert seen["query"] == payload
        run_kwargs = seen["runner"].run.call_args.kwargs
        assert run_kwargs["execution_mode"] == ExecutionMode.CALCULATE_BLOCKING_ALWAYS

    def test_missing_team_returns_without_raising(self):
        with mock.patch(f"{_MOD}.get_query_runner") as get_runner:
            revalidate_web_analytics_precompute(team_id=0, query={"kind": "WebOverviewQuery"})
        assert get_runner.call_count == 0

    def test_query_failure_is_swallowed(self):
        # A failed revalidation must not raise into Celery retry machinery — the next
        # stale hit after the debounce TTL (or the hourly warmer) converges instead.
        runner = mock.Mock()
        runner.run.side_effect = RuntimeError("clickhouse exploded")
        with mock.patch(f"{_MOD}.get_query_runner", return_value=runner):
            revalidate_web_analytics_precompute(team_id=self.team.pk, query={"kind": "WebOverviewQuery"})
