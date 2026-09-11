from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from freezegun import freeze_time
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.test.persons import create_person
from posthog.uuidt import uuid7

from products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute import (
    SESSIONS_INSERT_TEMPLATE,
    base_placeholders,
)


@freeze_time("2026-09-10T12:00:00Z")
class TestMarketingSessionsPrecompute(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand([(2,), (49,)])
    def test_pageview_bounds_include_the_full_session(self, duration_hours: int) -> None:
        start = datetime(2026, 9, 1, tzinfo=UTC)
        end = start + timedelta(days=1)
        first_pageview = end - timedelta(minutes=5)
        last_pageview = first_pageview + timedelta(hours=duration_hours)
        session_id = str(uuid7(int(first_pageview.timestamp() * 1000)))
        create_person(team=self.team, distinct_ids=["visitor"])
        for event, timestamp in [
            ("$pageview", first_pageview),
            ("$pageview", last_pageview),
            ("purchase", last_pageview + timedelta(minutes=1)),
        ]:
            _create_event(
                team=self.team,
                distinct_id="visitor",
                event=event,
                timestamp=timestamp,
                properties={"$session_id": session_id, "utm_source": "google"},
            )
        _create_event(
            team=self.team,
            distinct_id="visitor",
            event="$pageview",
            timestamp=end + timedelta(minutes=1),
            properties={"$session_id": str(uuid7(int((end + timedelta(minutes=1)).timestamp() * 1000)))},
        )
        flush_persons_and_events()

        response = execute_hogql_query(
            SESSIONS_INSERT_TEMPLATE,
            self.team,
            placeholders={
                **base_placeholders(),
                "time_window_min": ast.Constant(value=start),
                "time_window_max": ast.Constant(value=end),
            },
        )

        assert len(response.results) == 1
        row = dict(zip(response.columns, response.results[0]))
        assert row["session_id"] == session_id
        assert row["min_event_timestamp"] == first_pageview
        assert row["max_event_timestamp"] == last_pageview
