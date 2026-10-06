import re
import uuid
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
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
    @parameterized.expand([("UTC",), ("America/Santiago",), ("Asia/Kolkata",), ("Asia/Kathmandu",)])
    def test_session_start_windows_use_utc_boundaries(self, timezone: str) -> None:
        self.team.timezone = timezone
        start = datetime(2026, 9, 1, tzinfo=UTC)
        end = start + timedelta(days=1)
        create_person(team=self.team, distinct_ids=["visitor"])
        expected = []
        for seconds in (-1, 0, 86399, 86400):
            timestamp = start + timedelta(seconds=seconds)
            session_id = uuid7(int(timestamp.timestamp() * 1000))
            _create_event(
                team=self.team,
                distinct_id="visitor",
                event="$pageview",
                timestamp=timestamp,
                properties={"$session_id": str(session_id)},
            )
            if 0 <= seconds < 86400:
                expected.append((session_id.int, timestamp.replace(minute=0, second=0)))

        response = execute_hogql_query(
            SESSIONS_INSERT_TEMPLATE,
            self.team,
            placeholders={
                **base_placeholders(),
                "time_window_min": ast.Constant(value=start),
                "time_window_max": ast.Constant(value=end),
            },
        )
        assert response.columns is not None
        session_column = response.columns.index("session_id_v7")
        bucket_column = response.columns.index("period_bucket")
        assert sorted((row[session_column], row[bucket_column]) for row in response.results) == expected

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

    @parameterized.expand([(SessionTableVersion.V2,), (SessionTableVersion.V3,)])
    def test_window_refreshes_after_a_long_sessions_first_pageview(self, version: SessionTableVersion) -> None:
        self.team.modifiers = {"sessionTableVersion": version}
        start = time_machine.escape_hatch.datetime.datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=4)
        end = start + timedelta(days=1)
        opened_at = start + timedelta(hours=23)
        session_id = str(uuid7(int(opened_at.timestamp() * 1000)))
        create_person(team=self.team, distinct_ids=["long-session-visitor"])
        _create_event(
            team=self.team,
            distinct_id="long-session-visitor",
            event="$autocapture",
            timestamp=opened_at,
            properties={"$session_id": session_id},
        )
        flush_persons_and_events()

        with time_machine.travel(start + timedelta(days=3, minutes=35), tick=False):
            initial = ensure_marketing_sessions_precomputed(self.team, start, end)
            assert initial.ready, initial.errors

        with time_machine.travel(start + timedelta(days=3, hours=1), tick=False):
            _create_event(
                team=self.team,
                distinct_id="long-session-visitor",
                event="$pageview",
                timestamp=start + timedelta(days=3, hours=1),
                properties={"$session_id": session_id, "utm_campaign": "late-pageview"},
            )
            flush_persons_and_events()

        with time_machine.travel(start + timedelta(days=4, minutes=1), tick=False):
            assert not ensure_marketing_sessions_precomputed(self.team, start, end, run_inserts=False).ready
            refreshed = ensure_marketing_sessions_precomputed(self.team, start, end)
            assert refreshed.ready, refreshed.errors
            assert set(refreshed.job_ids).isdisjoint(initial.job_ids)
            assert sync_execute(
                "SELECT session_id_v7, pageview_count FROM web_sessions_dimensional_preaggregated "
                "WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s",
                {"team_id": self.team.pk, "job_ids": refreshed.job_ids},
            ) == [(uuid.UUID(session_id).int, 1)]


class TestSessionPrecomputeCoverageFailure(SimpleTestCase):
    def test_query_error_does_not_prove_session_coverage(self) -> None:
        with (
            patch(
                "products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute.create_default_modifiers_for_team",
                return_value=HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2),
            ),
            patch(
                "products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute.execute_hogql_query",
                return_value=HogQLQueryResponse(results=[], error="Coverage query failed"),
            ),
        ):
            result = ensure_marketing_sessions_precomputed(
                Team(id=1), datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC)
            )
        self.assertFalse(result.ready)
        self.assertEqual(result.job_ids, [])
        self.assertEqual(result.errors, ["Could not verify session precompute coverage"])
