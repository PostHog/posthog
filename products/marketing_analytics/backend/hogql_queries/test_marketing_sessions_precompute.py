import re
import uuid
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.schema_enums import SessionTableVersion
from posthog.test.persons import create_person
from posthog.uuidt import uuid7

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute import (
    SESSIONS_INSERT_TEMPLATE,
    base_placeholders,
    ensure_marketing_sessions_precomputed,
)


@time_machine.travel("2026-09-10T12:00:00Z", tick=False)
class TestMarketingSessionsPrecompute(ClickhouseTestMixin, APIBaseTest):
    def test_future_window_requires_refresh_when_it_starts(self) -> None:
        self.team.timezone = "America/Los_Angeles"
        start = datetime(2026, 9, 11, tzinfo=UTC)
        end = start + timedelta(hours=7)
        with time_machine.travel(start - timedelta(minutes=25), tick=False) as clock:
            warmed = ensure_marketing_sessions_precomputed(self.team, start, end)
            assert warmed.ready, warmed.errors
            assert warmed.job_ids
            cached = ensure_marketing_sessions_precomputed(self.team, start, end, run_inserts=False)
            assert cached.ready
            assert cached.job_ids == warmed.job_ids

            clock.shift(timedelta(minutes=25))
            for grace in (None, 6 * 60 * 60):
                cached = ensure_marketing_sessions_precomputed(
                    self.team, start, end, run_inserts=False, stale_while_revalidate_seconds=grace
                )
                assert not cached.ready
                assert not cached.job_ids

            clock.shift(timedelta(minutes=1))
            timestamp = datetime.now(UTC)
            session_id = uuid7(int(timestamp.timestamp() * 1000))
            create_person(team=self.team, distinct_ids=["new-window-visitor"])
            _create_event(
                team=self.team,
                distinct_id="new-window-visitor",
                event="$pageview",
                timestamp=timestamp,
                properties={"$session_id": str(session_id)},
            )
            flush_persons_and_events()
            refreshed = ensure_marketing_sessions_precomputed(self.team, start, end)
            assert refreshed.ready, refreshed.errors
            assert set(refreshed.job_ids).isdisjoint(warmed.job_ids)
            cached = ensure_marketing_sessions_precomputed(
                self.team, start, end, run_inserts=False, stale_while_revalidate_seconds=6 * 60 * 60
            )
            assert cached.ready
            assert cached.job_ids == refreshed.job_ids
            assert sync_execute(
                "SELECT session_id_v7 FROM web_sessions_dimensional_preaggregated "
                "WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s",
                {"team_id": self.team.pk, "job_ids": cached.job_ids},
            ) == [(session_id.int,)]

    @parameterized.expand(
        [
            (version, legacy_value)
            for version in (SessionTableVersion.V2, SessionTableVersion.V3)
            for legacy_value in (None, True, False)
        ]
    )
    def test_cookieless_rollout_reuses_jobs_after_cache_key_transition(
        self, version: SessionTableVersion, legacy_value: bool | None
    ) -> None:
        self.team.modifiers = {"sessionTableVersion": version}
        start = datetime(2026, 9, 1, tzinfo=UTC)
        end = start + timedelta(days=1)
        with patch(
            "products.web_analytics.backend.hogql_queries.cookieless_flag.resolve_cookieless_traffic_is_regular_modifier"
        ) as resolve:
            resolve.return_value = legacy_value
            legacy_modifiers = create_default_modifiers_for_team(self.team)
            legacy = ensure_precomputed(
                team=self.team,
                insert_query=SESSIONS_INSERT_TEMPLATE,
                time_range_start=start,
                time_range_end=end,
                ttl_seconds=90 * 24 * 60 * 60,
                table=LazyComputationTable.WEB_SESSIONS_DIMENSIONAL_PREAGGREGATED,
                modifiers=legacy_modifiers,
                cache_key_context={"modifiers": legacy_modifiers.model_dump_json(exclude_none=True)},
                placeholders=base_placeholders(),
            )
            assert legacy.ready, legacy.errors
            assert legacy.job_ids
            written = ensure_marketing_sessions_precomputed(self.team, start, end, run_inserts=False)
            if legacy_value is None:
                assert set(written.job_ids) == set(legacy.job_ids)
            else:
                assert not written.ready
                assert not written.job_ids
                written = ensure_marketing_sessions_precomputed(self.team, start, end)
                assert set(written.job_ids).isdisjoint(legacy.job_ids)
            assert written.ready, written.errors
            assert written.job_ids
            original_sql = None
            for enabled in (None, True, False):
                resolve.return_value = enabled
                response = execute_hogql_query(
                    SESSIONS_INSERT_TEMPLATE,
                    self.team,
                    placeholders={
                        **base_placeholders(),
                        "time_window_min": ast.Constant(value=start),
                        "time_window_max": ast.Constant(value=end),
                    },
                )
                assert response.clickhouse
                if original_sql is None:
                    original_sql = response.clickhouse
                assert response.clickhouse == original_sql
                cached = ensure_marketing_sessions_precomputed(self.team, start, end, run_inserts=False)
                assert cached.ready, cached.errors
                assert set(cached.job_ids) == set(written.job_ids)

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
        assert result.ready, result.errors
        assert sync_execute(
            "SELECT session_id_v7, pageview_count FROM web_sessions_dimensional_preaggregated "
            "WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s",
            {"team_id": self.team.pk, "job_ids": result.job_ids},
        ) == ([] if duration_hours > 72 else [(uuid.UUID(session_id).int, 2)])
        if duration_hours > 72:
            return

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
        assert cached.ready
        assert set(cached.job_ids) == set(result.job_ids)

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
