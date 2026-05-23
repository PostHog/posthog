import uuid
from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.schema import (
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    SessionPropertyFilter,
    SessionsV2JoinMode,
    WebAnalyticsSampling,
    WebOverviewQuery,
)

from posthog.models.utils import uuid7

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner


@override_settings(IN_UNIT_TESTING=True)
class TestWebOverviewLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

    def _enable_lazy(self):
        # Mock the org-level feature flag check to True so the gate accepts our test
        # team. Outside this context manager the default `posthoganalytics.feature_enabled`
        # returns False (no API key in tests), which models a flag-disabled org.
        return patch(
            "products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute.posthoganalytics.feature_enabled",
            return_value=True,
        )

    def _seed_two_sessions(self) -> None:
        # p1 has two pageviews in one session, p2 has a single pageview (bounce).
        s1 = str(uuid7("2024-01-02"))
        s2 = str(uuid7("2024-01-03"))
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-02T10:00:00Z",
            properties={"$session_id": s1, "$host": "example.com", "$current_url": "https://example.com/a"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-02T10:05:00Z",
            properties={"$session_id": s1, "$host": "example.com", "$current_url": "https://example.com/b"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2024-01-03T11:00:00Z",
            properties={"$session_id": s2, "$host": "other.com", "$current_url": "https://other.com/x"},
        )
        self._wait_for_raw_sessions(expected=2)

    def _wait_for_raw_sessions_rows(self, expected: int, timeout_s: float = 10.0) -> None:
        # Variant of `_wait_for_raw_sessions` that polls total row count instead
        # of distinct session_id_v7 count. Useful when a test adds a *late event
        # to an existing session* — the MV still emits a new row, so the row
        # count goes up even though distinct session_id_v7 stays the same.
        import time

        from posthog.clickhouse.client import sync_execute

        deadline = time.monotonic() + timeout_s
        last_count = -1
        while time.monotonic() < deadline:
            row = sync_execute(
                "SELECT count() FROM raw_sessions WHERE team_id = %(tid)s",
                {"tid": self.team.pk},
            )
            last_count = int(row[0][0]) if row else 0
            if last_count >= expected:
                return
            time.sleep(0.05)
        raise AssertionError(
            f"raw_sessions row count did not reach expected for team_id={self.team.pk} "
            f"within {timeout_s}s — got {last_count}, expected >= {expected}."
        )

    def _wait_for_raw_sessions(self, expected: int, timeout_s: float = 10.0) -> None:
        # In CI, `bulk_create_events` writes directly to `sharded_events`, which
        # triggers the `raw_sessions_mv` materialized view. Locally that
        # propagates fast enough that the lazy INSERT's `session.*` join sees
        # the rows; in CI the lazy INSERT runs before the MV-produced
        # `raw_sessions` rows are visible to the SELECT, and the HAVING
        # clause filters everything out — producing zero preagg rows despite
        # the events being present (verified via `_dump_lazy_state` in CI).
        # Mirrors the post-INSERT polling pattern from #59551.
        import time

        from posthog.clickhouse.client import sync_execute

        deadline = time.monotonic() + timeout_s
        last_count = -1
        while time.monotonic() < deadline:
            row = sync_execute(
                "SELECT countDistinct(session_id_v7) FROM raw_sessions WHERE team_id = %(tid)s",
                {"tid": self.team.pk},
            )
            last_count = int(row[0][0]) if row else 0
            if last_count >= expected:
                return
            time.sleep(0.05)
        raise AssertionError(
            f"raw_sessions did not reach expected count for team_id={self.team.pk} "
            f"within {timeout_s}s — got {last_count}, expected >= {expected}. "
            "Sessions MV may not be firing on test inserts."
        )

    def _build_query(
        self,
        date_from: str = "2024-01-01",
        date_to: str = "2024-01-07",
        properties: list | None = None,
        compare: bool = False,
        conversion_goal=None,
        sampling: WebAnalyticsSampling | None = None,
        opt_in_precompute: bool = True,
    ) -> WebOverviewQuery:
        return WebOverviewQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            compareFilter=CompareFilter(compare=compare) if compare else None,
            conversionGoal=conversion_goal,
            sampling=sampling,
            useWebAnalyticsPrecompute=opt_in_precompute,
        )

    def _run(self, query: WebOverviewQuery):
        return WebOverviewQueryRunner(team=self.team, query=query).calculate()

    def _dump_lazy_state(self) -> str:
        # Diagnostic helper: when a lazy/raw mismatch fires on CI but passes
        # locally, surface what ClickHouse + Postgres actually contain for this
        # team so we can tell INSERT-failed-empty apart from
        # READ-can't-see-the-rows. Keep concise; lands in assert messages.
        from posthog.clickhouse.client import sync_execute

        team_id = self.team.pk
        try:
            preagg = sync_execute(
                "SELECT count(), countDistinct(job_id), min(time_window_start), max(time_window_start) "
                "FROM web_overview_preaggregated WHERE team_id = %(team_id)s",
                {"team_id": team_id},
            )
            preagg_summary = (
                f"rows={preagg[0][0]} distinct_jobs={preagg[0][1]} window_range=[{preagg[0][2]}, {preagg[0][3]}]"
            )
        except Exception as exc:
            preagg_summary = f"ERROR querying preagg: {type(exc).__name__}: {exc}"

        try:
            events_count = sync_execute(
                "SELECT count(), min(timestamp), max(timestamp) FROM events WHERE team_id = %(team_id)s",
                {"team_id": team_id},
            )
            events_summary = f"count={events_count[0][0]} timestamp_range=[{events_count[0][1]}, {events_count[0][2]}]"
        except Exception as exc:
            events_summary = f"ERROR: {type(exc).__name__}: {exc}"

        # raw_sessions is populated by an MV from sharded_events. If empty, the
        # MV didn't fire (or didn't fire in time) — that explains why the lazy
        # INSERT's `session.$start_timestamp` join returns NULL and the HAVING
        # clause filters everything out.
        try:
            rs = sync_execute(
                "SELECT count(), countDistinct(session_id_v7) FROM raw_sessions WHERE team_id = %(team_id)s",
                {"team_id": team_id},
            )
            raw_sessions_summary = f"rows={rs[0][0]} distinct_session_ids={rs[0][1]}"
        except Exception as exc:
            raw_sessions_summary = f"ERROR: {type(exc).__name__}: {exc}"

        jobs = list(PreaggregationJob.objects.filter(team_id=team_id).values_list("status", "id", "query_hash"))
        jobs_summary = ", ".join(f"{s}:{str(jid)[:8]}:{qh[:8]}" for s, jid, qh in jobs) or "none"

        return (
            f"\n[CH state for team_id={team_id}] events: {events_summary} | "
            f"raw_sessions: {raw_sessions_summary} | preagg: {preagg_summary} | "
            f"pg_jobs=[{jobs_summary}]"
        )

    def _execute_sync_lazy_insert(
        self,
        runner: "WebOverviewQueryRunner",
        time_window_min: datetime,
        time_window_max: datetime,
        ttl_seconds: int = 7 * 24 * 60 * 60,
    ) -> uuid.UUID:
        # Synchronous twin of `ensure_web_overview_precomputed`. Builds the
        # *real* INSERT_QUERY_TEMPLATE via `_build_manual_insert_sql` (same SQL
        # the framework runs in prod) and executes it via `sync_execute`. No
        # `PreaggregationJob` row is created — we own the synthetic `job_id`
        # and feed it to `execute_read_query`.
        #
        # Removes the framework's async/orchestration surface (PG job
        # lifecycle, missing-window chunking, cross-process state) from these
        # tests so the round-trip assertion isolates "is the SQL correct?"
        # from "does the framework wire it up?". The framework smoke test is
        # `test_unfiltered_round_trip_creates_precompute_job`.
        from dataclasses import dataclass

        from posthog.hogql import ast

        from posthog.clickhouse.client import sync_execute

        from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
            LazyComputationTable,
            _build_manual_insert_sql,
            _get_insert_settings,
        )
        from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import (
            INSERT_QUERY_TEMPLATE,
            SESSION_FORWARD_PAD_MINUTES,
            _events_session_id_expr,
            _test_account_filter_expr,
            _user_filter_expr,
        )

        @dataclass
        class _StubJob:
            id: uuid.UUID
            time_range_start: datetime
            time_range_end: datetime
            expires_at: datetime

        job = _StubJob(
            id=uuid.uuid4(),
            time_range_start=time_window_min,
            time_range_end=time_window_max,
            expires_at=django_timezone.now() + timedelta(seconds=ttl_seconds),
        )

        base_placeholders: dict[str, ast.Expr] = {
            "events_session_id": _events_session_id_expr(runner),
            "event_type_filter": runner.event_type_expr,
            "user_filter": _user_filter_expr(runner),
            "test_account_filter": _test_account_filter_expr(runner),
            "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
        }

        sql, values = _build_manual_insert_sql(
            team=self.team,
            job=job,
            insert_query=INSERT_QUERY_TEMPLATE,
            table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
            base_placeholders=base_placeholders,
        )
        sync_execute(sql, values, settings=_get_insert_settings(self.team.id))
        return job.id

    @freeze_time("2024-01-15T12:00:00Z")
    def test_unfiltered_round_trip_creates_precompute_job(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())

        jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
        assert len(jobs) > 0, "expected at least one precompute job to be created"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_result_matches_raw_result(self):
        """Run the same query through the raw events scan and the lazy precompute
        path (synchronous twin) and assert the metrics match.

        The lazy path here bypasses the `PreaggregationJob` orchestration via
        `_execute_sync_lazy_insert`: same INSERT_QUERY_TEMPLATE, same
        `execute_read_query`, no framework async surface."""
        from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import execute_read_query

        self._seed_two_sessions()

        # Path A: raw events scan (no lazy gate).
        raw_response = self._run(self._build_query())
        raw_visitors = raw_response.results[0].value
        raw_views = raw_response.results[1].value
        raw_sessions = raw_response.results[2].value

        # Path B: synchronous lazy precompute INSERT-SELECT + READ.
        runner = WebOverviewQueryRunner(team=self.team, query=self._build_query())
        date_from = runner.query_date_range.date_from().astimezone(UTC)
        date_to = runner.query_date_range.date_to().astimezone(UTC)
        time_window_min = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
        time_window_max = datetime(date_to.year, date_to.month, date_to.day, tzinfo=UTC) + timedelta(days=1)

        job_id = self._execute_sync_lazy_insert(runner, time_window_min, time_window_max)

        rows = execute_read_query(
            team_id=self.team.pk,
            job_ids=[str(job_id)],
            current_start_utc=date_from,
            current_end_utc=date_to,
            previous_start_utc=None,
            previous_end_utc=None,
        )
        # _READ_SQL returns one row: [unique_users, prev_unique_users, views, prev_views,
        # sessions, prev_sessions, avg_duration, prev_avg_duration, bounce_rate, prev_bounce_rate]
        lazy_visitors, _, lazy_views, _, lazy_sessions, *_ = rows[0]

        state = self._dump_lazy_state()
        assert lazy_visitors == raw_visitors, f"visitors mismatch: lazy={lazy_visitors}, raw={raw_visitors}{state}"
        assert lazy_views == raw_views, f"views mismatch: lazy={lazy_views}, raw={raw_views}{state}"
        assert lazy_sessions == raw_sessions, f"sessions mismatch: lazy={lazy_sessions}, raw={raw_sessions}{state}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_host_filter_gets_distinct_cache_entry(self):
        self._seed_two_sessions()
        host_filter = EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)

        with self._enable_lazy():
            self._run(self._build_query())
            unfiltered_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(self._build_query(properties=[host_filter]))
            filtered_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert unfiltered_jobs, "expected unfiltered run to create at least one job"
        assert filtered_jobs, "expected host-filtered run to create at least one job"
        assert unfiltered_jobs.isdisjoint(filtered_jobs), (
            f"unfiltered and host-filtered runs must produce distinct cache keys, "
            f"got overlap: {unfiltered_jobs & filtered_jobs}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_distinct_host_values_get_distinct_cache_entries(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(
                self._build_query(
                    properties=[EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)]
                )
            )
            example_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(
                self._build_query(
                    properties=[EventPropertyFilter(key="$host", value="other.com", operator=PropertyOperator.EXACT)]
                )
            )
            other_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert example_jobs.isdisjoint(other_jobs), (
            f"different $host values must produce distinct cache keys, got overlap: {example_jobs & other_jobs}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_disqualifying_filter_falls_through(self):
        self._seed_two_sessions()
        # $pathname is not in the MVP allowlist → gate returns False → no job created.
        with self._enable_lazy():
            self._run(
                self._build_query(
                    properties=[
                        EventPropertyFilter(key="$pathname", value="/a", operator=PropertyOperator.EXACT),
                    ]
                )
            )

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_session_property_falls_through(self):
        # Session-level filters never qualify for MVP — only EventPropertyFilter on $host.
        with self._enable_lazy():
            self._run(
                self._build_query(
                    properties=[
                        SessionPropertyFilter(key="$channel_type", value="Direct", operator=PropertyOperator.EXACT),
                    ]
                )
            )

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_sampling_falls_through(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(sampling=WebAnalyticsSampling(enabled=True)))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_disabled_team_falls_through(self):
        # Both gates closed: org feature flag off AND query opt-in not set.
        self._seed_two_sessions()
        self._run(self._build_query(opt_in_precompute=False))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_query_optin_alone_falls_through_when_org_flag_disabled(self):
        # `query.useWebAnalyticsPrecompute=True` BUT the
        # `web-analytics-precompute-toggle` feature flag is off. Should
        # fall through — the flag is the operator-controlled rollout gate.
        self._seed_two_sessions()
        self._run(self._build_query(opt_in_precompute=True))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_org_flag_alone_falls_through_when_query_not_opted_in(self):
        # Org feature flag is on BUT the query param is not set (the team hasn't
        # enabled the "Allow precompute" toggle in the ScenePanel). Should fall
        # through — the param is the per-team opt-in / kill switch.
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(opt_in_precompute=False))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_cache_hit_on_second_call(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())
            first_run_jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
            first_run_summary = [(str(j.id), j.status, j.error or "") for j in first_run_jobs]

            self._run(self._build_query())
            second_run_jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
            second_run_summary = [(str(j.id), j.status, j.error or "") for j in second_run_jobs]

        # The second call should not create *new* successful jobs — it should reuse ready ones.
        first_ready_ids = {jid for jid, status, _err in first_run_summary if status == PreaggregationJob.Status.READY}
        new_jobs_in_second = {jid for jid, _, _ in second_run_summary} - {jid for jid, _, _ in first_run_summary}

        assert first_ready_ids, (
            f"first run should have produced at least one READY job, statuses were: {first_run_summary}"
        )
        # Any newly-created jobs in the second call must be replacements for FAILED first-run jobs,
        # not duplicates of READY ones.
        for new_id in new_jobs_in_second:
            new_job = next(j for j in second_run_jobs if str(j.id) == new_id)
            assert new_job.status == PreaggregationJob.Status.READY
        # Most importantly: no READY job from the first run should be discarded.
        ready_jobs_preserved = first_ready_ids.issubset({jid for jid, _, _ in second_run_summary})
        assert ready_jobs_preserved, (
            f"second run dropped some first-run READY jobs. first: {first_run_summary}, second: {second_run_summary}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_compare_to_period_reuses_cache(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())
            no_compare_jobs = {str(j.id) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

            self._run(self._build_query(compare=True))
            after_compare_jobs = {str(j.id) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        # Compare reads from the same precomputed window with a wider date range, so
        # it should reuse existing jobs and not multiply them.
        assert no_compare_jobs.issubset(after_compare_jobs)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_compare_to_period_returns_real_previous_values(self):
        """Regression: ensure compare-period metrics come from real precomputed
        previous-period data, not 0/NaN. The bug surfaced when the lazy path
        only precomputed the current window, leaving the read query with no
        rows to merge for the `prev_*` columns. Compare to the same query
        evaluated through the raw events path to assert parity."""
        # Current period: standard 2-session fixture (Jan 2 + Jan 3).
        self._seed_two_sessions()
        # Previous period: 1 extra session in the 7 days before Jan 1.
        _create_person(team_id=self.team.pk, distinct_ids=["prev_p1"], properties={"name": "prev_p1"})
        prev_session = str(uuid7("2023-12-28"))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="prev_p1",
            timestamp="2023-12-28T10:00:00Z",
            properties={
                "$session_id": prev_session,
                "$host": "example.com",
                "$current_url": "https://example.com/old",
            },
        )
        self._wait_for_raw_sessions(expected=3)  # 2 from _seed + 1 prev_p1

        # Path A: raw events scan, compare=True. Ground truth for previous values.
        raw_response = self._run(self._build_query(compare=True))
        raw_visitors = raw_response.results[0]
        raw_sessions = raw_response.results[2]

        # Path B: lazy precompute, compare=True. Must match the raw response.
        with self._enable_lazy():
            lazy_response = self._run(self._build_query(compare=True))
        lazy_visitors = lazy_response.results[0]
        lazy_sessions = lazy_response.results[2]

        assert lazy_visitors.previous == raw_visitors.previous, (
            f"previous visitors mismatch: lazy={lazy_visitors.previous}, raw={raw_visitors.previous}. "
            f"If lazy is 0/None, the previous-period precompute is missing."
        )
        assert lazy_sessions.previous == raw_sessions.previous, (
            f"previous sessions mismatch: lazy={lazy_sessions.previous}, raw={raw_sessions.previous}."
        )
        # Sanity: the raw path must actually report > 0 in the previous period
        # — otherwise the assertion above could be a vacuous 0 == 0 and miss the
        # regression we're trying to catch.
        assert raw_visitors.previous and raw_visitors.previous > 0, (
            f"raw previous visitors should be > 0 with seeded prev_p1 event, got {raw_visitors.previous}"
        )

    # --- Group A: timezone correctness --------------------------------------

    @parameterized.expand(
        [
            ("utc", "UTC"),
            ("pacific", "America/Los_Angeles"),
            ("tokyo", "Asia/Tokyo"),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_result_matches_raw_for_whole_hour_timezones(self, _name: str, team_tz: str) -> None:
        """Whole-hour-offset teams must produce the same metrics through the lazy and raw paths.

        Lazy side uses `_execute_sync_lazy_insert` so the comparison isolates SQL
        correctness from the framework's async orchestration."""
        from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import execute_read_query

        self.team.timezone = team_tz
        self.team.save()
        self._seed_two_sessions()

        raw_response = self._run(self._build_query())
        raw_values = [(r.key, r.value) for r in raw_response.results]

        runner = WebOverviewQueryRunner(team=self.team, query=self._build_query())
        date_from = runner.query_date_range.date_from().astimezone(UTC)
        date_to = runner.query_date_range.date_to().astimezone(UTC)
        time_window_min = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
        time_window_max = datetime(date_to.year, date_to.month, date_to.day, tzinfo=UTC) + timedelta(days=1)

        job_id = self._execute_sync_lazy_insert(runner, time_window_min, time_window_max)

        rows = execute_read_query(
            team_id=self.team.pk,
            job_ids=[str(job_id)],
            current_start_utc=date_from,
            current_end_utc=date_to,
            previous_start_utc=None,
            previous_end_utc=None,
        )
        # _READ_SQL returns one row; current-period metrics are at indices 0/2/4/6/8.
        cur = rows[0]
        lazy_values = [
            (raw_values[0][0], cur[0]),  # visitors
            (raw_values[1][0], cur[2]),  # views
            (raw_values[2][0], cur[4]),  # sessions
            (raw_values[3][0], cur[6]),  # session duration
            (raw_values[4][0], cur[8] * 100 if cur[8] is not None else None),  # bounce rate (% to match raw)
        ]
        assert lazy_values == raw_values, (
            f"lazy/raw mismatch for {team_tz}: raw={raw_values}, lazy={lazy_values}{self._dump_lazy_state()}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_half_hour_offset_timezone_falls_through(self):
        # IST is UTC+5:30 — hourly UTC buckets can't represent the team-local
        # midnight, so the gate must refuse.
        self.team.timezone = "Asia/Kolkata"
        self.team.save()
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    # --- Group B: gate strictness -------------------------------------------

    @freeze_time("2024-01-15T12:00:00Z")
    def test_multiple_host_filters_fall_through(self):
        # Gate accepts at most one user-supplied property — multi-host inputs
        # collide on a single-filter cache key and must be rejected.
        self._seed_two_sessions()
        host_a = EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)
        host_b = EventPropertyFilter(key="$host", value="other.com", operator=PropertyOperator.EXACT)
        with self._enable_lazy():
            self._run(self._build_query(properties=[host_a, host_b]))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_uuid_session_mode_falls_through(self):
        # `events.$session_id_uuid` would produce `uniqState(UUID)` which the
        # `(uniq, String)` column rejects non-retryably. Gate must refuse.
        self._seed_two_sessions()
        query = self._build_query()
        query.modifiers = HogQLQueryModifiers(sessionsV2JoinMode=SessionsV2JoinMode.UUID)
        with self._enable_lazy():
            self._run(query)

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @parameterized.expand(
        [
            ("none_value", None),
            ("list_value", ["example.com", "other.com"]),
            ("empty_string", ""),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_non_string_host_value_falls_through(self, _name: str, host_value) -> None:
        self._seed_two_sessions()
        prop = EventPropertyFilter(key="$host", value=host_value, operator=PropertyOperator.EXACT)
        with self._enable_lazy():
            self._run(self._build_query(properties=[prop]))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_window_over_max_days_falls_through(self):
        # 365 days >> MAX_PRECOMPUTE_DAYS — gate refuses to avoid spawning
        # hundreds of daily INSERT jobs in one request.
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(date_from="2023-01-01", date_to="2024-01-07"))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    # --- Group C: forward-only pad + compare readiness ---------------------

    @freeze_time("2024-01-15T12:00:00Z")
    def test_session_just_after_window_start_attributed_correctly(self):
        # Forward-only pad regression: a session starting near the leading edge
        # of a daily UTC bucket must still aggregate its full set of events.
        # If the inner-SELECT loses the trailing events, sessions/duration/views
        # would not match the raw path.
        session_id = str(uuid7("2024-01-02"))
        _create_person(team_id=self.team.pk, distinct_ids=["edge_p1"], properties={"name": "edge_p1"})
        for offset_min in (5, 15, 30):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="edge_p1",
                timestamp=f"2024-01-02T00:{offset_min:02d}:00Z",
                properties={
                    "$session_id": session_id,
                    "$host": "example.com",
                    "$current_url": f"https://example.com/p{offset_min}",
                },
            )
        self._wait_for_raw_sessions(expected=1)

        from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import execute_read_query

        raw_response = self._run(self._build_query(date_from="2024-01-02", date_to="2024-01-02"))
        raw_values = [(r.key, r.value) for r in raw_response.results]

        runner = WebOverviewQueryRunner(
            team=self.team, query=self._build_query(date_from="2024-01-02", date_to="2024-01-02")
        )
        date_from = runner.query_date_range.date_from().astimezone(UTC)
        date_to = runner.query_date_range.date_to().astimezone(UTC)
        time_window_min = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
        time_window_max = datetime(date_to.year, date_to.month, date_to.day, tzinfo=UTC) + timedelta(days=1)

        job_id = self._execute_sync_lazy_insert(runner, time_window_min, time_window_max)

        rows = execute_read_query(
            team_id=self.team.pk,
            job_ids=[str(job_id)],
            current_start_utc=date_from,
            current_end_utc=date_to,
            previous_start_utc=None,
            previous_end_utc=None,
        )
        cur = rows[0]
        lazy_values = [
            (raw_values[0][0], cur[0]),  # visitors
            (raw_values[1][0], cur[2]),  # views
            (raw_values[2][0], cur[4]),  # sessions
            (raw_values[3][0], cur[6]),  # session duration
            (raw_values[4][0], cur[8] * 100 if cur[8] is not None else None),  # bounce rate (% to match raw)
        ]

        assert lazy_values == raw_values, (
            f"forward-only pad parity broken: raw={raw_values}, lazy={lazy_values}{self._dump_lazy_state()}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_compare_period_falls_back_when_previous_not_ready(self):
        # If the previous-period precompute hasn't reached READY across all jobs,
        # we must not read — the read would silently return 0/NaN for `prev_*`
        # columns. The lazy path returns None to signal fall-back to raw.
        first_call = {"done": False}

        def fake_ensure(runner, time_range_start, time_range_end):
            if not first_call["done"]:
                first_call["done"] = True
                return LazyComputationResult(ready=True, job_ids=[uuid.uuid4()])
            return LazyComputationResult(ready=False, job_ids=[uuid.uuid4()])

        from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import (
            execute_lazy_precomputed_read,
        )

        with (
            self._enable_lazy(),
            patch(
                "products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute.ensure_web_overview_precomputed",
                side_effect=fake_ensure,
            ),
        ):
            runner = WebOverviewQueryRunner(team=self.team, query=self._build_query(compare=True))
            result = execute_lazy_precomputed_read(runner)

        assert result is None, f"expected fall-back to raw when previous precompute not ready, got {result!r}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_recomputation_picks_up_late_events_changing_bounce_and_duration(self):
        """After a late event arrives, re-running the lazy INSERT must reflect
        the new session state:
          • bounce flips from 100% → 0% when a second pageview lands
          • session_duration grows from 0 → non-zero
          • views grows from 1 → 2

        Uses `_execute_sync_lazy_insert` with a fresh `job_id` for each run.
        The stale precomputed row stays in ClickHouse with the old `job_id`;
        the new read passes the new `job_id`, so the `job_id IN (...)` filter
        in `_READ_SQL` naturally isolates the runs."""
        from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import execute_read_query

        session_id = str(uuid7("2024-01-02"))
        _create_person(team_id=self.team.pk, distinct_ids=["recompute_p1"], properties={"name": "recompute_p1"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="recompute_p1",
            timestamp="2024-01-02T10:00:00Z",
            properties={
                "$session_id": session_id,
                "$host": "example.com",
                "$current_url": "https://example.com/first",
            },
        )
        self._wait_for_raw_sessions(expected=1)

        runner = WebOverviewQueryRunner(
            team=self.team, query=self._build_query(date_from="2024-01-02", date_to="2024-01-02")
        )
        date_from = runner.query_date_range.date_from().astimezone(UTC)
        date_to = runner.query_date_range.date_to().astimezone(UTC)
        time_window_min = datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC)
        time_window_max = datetime(date_to.year, date_to.month, date_to.day, tzinfo=UTC) + timedelta(days=1)

        # First run: single pageview = bounce (100%), zero duration.
        first_job_id = self._execute_sync_lazy_insert(runner, time_window_min, time_window_max)
        first_rows = execute_read_query(
            team_id=self.team.pk,
            job_ids=[str(first_job_id)],
            current_start_utc=date_from,
            current_end_utc=date_to,
            previous_start_utc=None,
            previous_end_utc=None,
        )
        first_cur = first_rows[0]
        assert first_cur[2] == 1.0, f"first run views should be 1, got {first_cur[2]}"
        # READ returns bounce as a 0..1 fraction; runner multiplies by 100 for the response.
        assert first_cur[8] == 1.0, f"first run bounce rate should be 1.0 (= 100%), got {first_cur[8]}"

        # Late event arrives, extending the same session.
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="recompute_p1",
            timestamp="2024-01-02T10:15:00Z",
            properties={
                "$session_id": session_id,
                "$host": "example.com",
                "$current_url": "https://example.com/second",
            },
        )
        # Force the late event into ClickHouse and wait for the sessions MV to
        # materialize it as a second raw_sessions row (same session_id_v7, so
        # distinct count stays at 1 — the MV emits a new row per event-batch
        # before ReplacingMergeTree collapses them). Without this, the next
        # INSERT-SELECT runs before the MV has reflected the late event and the
        # join only sees the first event — recomputed views stays at 1.
        flush_persons_and_events()
        self._wait_for_raw_sessions_rows(expected=2)

        # Second run: fresh job_id, same range. ReplacingMergeTree keeps the
        # stale row at the old job_id; the new read filters by the new job_id.
        second_job_id = self._execute_sync_lazy_insert(runner, time_window_min, time_window_max)
        assert second_job_id != first_job_id, "recomputation should use a fresh job_id"

        second_rows = execute_read_query(
            team_id=self.team.pk,
            job_ids=[str(second_job_id)],
            current_start_utc=date_from,
            current_end_utc=date_to,
            previous_start_utc=None,
            previous_end_utc=None,
        )
        second_cur = second_rows[0]
        state = self._dump_lazy_state()
        assert second_cur[2] == 2.0, f"recomputed views should be 2, got {second_cur[2]}{state}"
        assert second_cur[8] == 0.0, f"recomputed bounce rate should flip to 0 (= 0%), got {second_cur[8]}{state}"
        assert second_cur[6] is not None and second_cur[6] > 0, (
            f"recomputed session duration should be > 0, got {second_cur[6]}{state}"
        )

        # Cross-check parity vs the raw events path after the late event.
        # READ row indices: 0=visitors 2=views 4=sessions 6=duration 8=bounce (fraction);
        # the runner multiplies bounce by 100 for the response, so do the same here.
        raw_resp = self._run(self._build_query(date_from="2024-01-02", date_to="2024-01-02"))
        raw_metrics = {r.key: r.value for r in raw_resp.results}
        bounce_lazy = second_cur[8] * 100 if second_cur[8] is not None else None
        for metric, lazy_val in (
            ("visitors", second_cur[0]),
            ("views", second_cur[2]),
            ("sessions", second_cur[4]),
            ("session duration", second_cur[6]),
            ("bounce rate", bounce_lazy),
        ):
            assert lazy_val == raw_metrics[metric], (
                f"recomputed lazy != raw for {metric}: lazy={lazy_val}, raw={raw_metrics[metric]}"
            )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_falls_back_when_current_period_not_ready(self):
        # Symmetric to the previous test: if the current-period precompute
        # hasn't reached READY, the read would scan empty buckets. Fall back.
        from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import (
            execute_lazy_precomputed_read,
        )

        with (
            self._enable_lazy(),
            patch(
                "products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute.ensure_web_overview_precomputed",
                return_value=LazyComputationResult(ready=False, job_ids=[uuid.uuid4()]),
            ),
        ):
            runner = WebOverviewQueryRunner(team=self.team, query=self._build_query())
            result = execute_lazy_precomputed_read(runner)

        assert result is None, f"expected fall-back to raw when current precompute not ready, got {result!r}"
