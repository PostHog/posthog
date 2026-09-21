import re
import uuid
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.schema_enums import SessionTableVersion
from posthog.test.persons import create_person
from posthog.uuidt import uuid7

from products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute import (
    SESSIONS_INSERT_TEMPLATE,
    base_placeholders,
    ensure_marketing_sessions_precomputed,
)


@time_machine.travel("2026-09-10T12:00:00Z", tick=False)
class TestMarketingSessionsPrecompute(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [(version, hours) for version in (SessionTableVersion.V2, SessionTableVersion.V3) for hours in (2, 49, 97)]
    )
    def test_pageview_bounds_include_the_full_session(self, version: SessionTableVersion, duration_hours: int) -> None:
        self.team.modifiers = {"sessionTableVersion": version}
        start = datetime(2026, 9, 1, tzinfo=UTC)
        end = start + timedelta(days=1)
        first_pageview = start + timedelta(minutes=30) if duration_hours > 72 else end - timedelta(minutes=5)
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

        result = ensure_marketing_sessions_precomputed(self.team, start + timedelta(hours=1), end)
        if duration_hours > 72:
            assert not result.ready
            assert not result.job_ids
            return
        assert result.ready
        assert sync_execute(
            "SELECT session_id_v7, pageview_count FROM web_sessions_dimensional_preaggregated "
            "WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s",
            {"team_id": self.team.pk, "job_ids": result.job_ids},
        ) == [(uuid.UUID(session_id).int, 2)]

        response = execute_hogql_query(
            SESSIONS_INSERT_TEMPLATE,
            self.team,
            modifiers=HogQLQueryModifiers(sessionTableVersion=version),
            placeholders={
                **base_placeholders(),
                "time_window_min": ast.Constant(value=start),
                "time_window_max": ast.Constant(value=end),
            },
        )

        assert len(response.results) == 1
        assert response.columns is not None
        row = dict(zip(response.columns, response.results[0]))
        assert row["session_id_v7"] == uuid.UUID(session_id).int
        assert row["min_event_timestamp"] == first_pageview
        assert row["max_event_timestamp"] == last_pageview
        assert row["pageview_count"] == 2

        sessions_scans = re.findall(
            r"FROM\s+raw_sessions(?:_v3)?\s+WHERE(.*?)GROUP BY", response.clickhouse or "", re.S
        )
        assert sessions_scans
        for where in sessions_scans:
            assert "session_timestamp" in where if version == SessionTableVersion.V3 else "session_id_v7, 80" in where

        _create_event(
            team=self.team,
            distinct_id="visitor",
            event="$pageview",
            timestamp=first_pageview + timedelta(hours=97),
            properties={"$session_id": session_id},
        )
        flush_persons_and_events()
        cached = ensure_marketing_sessions_precomputed(self.team, start, end, run_inserts=False)
        assert not cached.ready
        assert not cached.job_ids
