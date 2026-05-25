import uuid

import unittest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings

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

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner


@override_settings(IN_UNIT_TESTING=True)
class TestWebOverviewLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        # The lazy framework derives `expires_at` from the (frozen) test clock, so
        # precompute rows are "born expired" relative to the real ClickHouse server
        # clock. Stop TTL merges on the precompute table so those parts are not
        # dropped in the window between the precompute INSERT and the read.
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_overview_preaggregated")

    def _enable_lazy(self):
        # Mock the org-level feature flag check to True so the gate accepts our test
        # team. Outside this context manager the default `posthoganalytics.feature_enabled`
        # returns False (no API key in tests), which models a flag-disabled org.
        return patch(
            "products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute.posthoganalytics.feature_enabled",
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

    @freeze_time("2024-01-15T12:00:00Z")
    def test_unfiltered_round_trip_creates_precompute_job(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())

        jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
        assert len(jobs) > 0, "expected at least one precompute job to be created"

    @unittest.skip(
        "Flaky on CI since #59075 — lazy path returns empty rows despite READY job. "
        "Suspected read-after-write visibility on Distributed table, but global "
        "insert_distributed_sync=1 is already set in users-dev.xml. Root cause under investigation."
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_result_matches_raw_result(self):
        """Run the same query with and without the lazy path enabled, assert results match."""
        self._seed_two_sessions()

        # Path A: raw events scan (no lazy gate).
        raw_response = self._run(self._build_query())
        raw_visitors = raw_response.results[0].value
        raw_views = raw_response.results[1].value
        raw_sessions = raw_response.results[2].value

        # Path B: lazy precompute.
        with self._enable_lazy():
            lazy_response = self._run(self._build_query())

        # Confirm we actually went through the lazy path.
        ready_jobs = PreaggregationJob.objects.filter(
            team_id=self.team.pk, status=PreaggregationJob.Status.READY
        ).count()
        assert ready_jobs > 0, "expected at least one READY precompute job"

        lazy_visitors = lazy_response.results[0].value
        lazy_views = lazy_response.results[1].value
        lazy_sessions = lazy_response.results[2].value

        assert lazy_visitors == raw_visitors, f"visitors mismatch: lazy={lazy_visitors}, raw={raw_visitors}"
        assert lazy_views == raw_views, f"views mismatch: lazy={lazy_views}, raw={raw_views}"
        assert lazy_sessions == raw_sessions, f"sessions mismatch: lazy={lazy_sessions}, raw={raw_sessions}"

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
    @unittest.skip(
        "Flaky on CI since #59075 — same root cause as test_lazy_result_matches_raw_result. "
        "Pacific variant is the most reproducible failure. The previous skip in #59614 was "
        "above @parameterized.expand, so the parameterized variants kept running and failing. "
        "Root cause under investigation."
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_result_matches_raw_for_whole_hour_timezones(self, _name: str, team_tz: str) -> None:
        """Whole-hour-offset teams must produce the same metrics through the lazy and raw paths."""
        self.team.timezone = team_tz
        self.team.save()
        self._seed_two_sessions()

        raw_response = self._run(self._build_query())
        raw_values = [(r.key, r.value) for r in raw_response.results]

        with self._enable_lazy():
            lazy_response = self._run(self._build_query())

        ready_jobs = PreaggregationJob.objects.filter(
            team_id=self.team.pk, status=PreaggregationJob.Status.READY
        ).count()
        assert ready_jobs > 0, f"expected READY precompute job for {team_tz}, got 0"

        lazy_values = [(r.key, r.value) for r in lazy_response.results]
        assert lazy_values == raw_values, f"lazy/raw mismatch for {team_tz}: raw={raw_values}, lazy={lazy_values}"

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

    @unittest.skip(
        "Flaky on CI since #59075 — same intermittent empty-result pattern as the other "
        "round-trip tests in this file. Missed by #59614. Root cause under investigation."
    )
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

        raw_response = self._run(self._build_query(date_from="2024-01-02", date_to="2024-01-02"))
        raw_values = [(r.key, r.value) for r in raw_response.results]

        with self._enable_lazy():
            lazy_response = self._run(self._build_query(date_from="2024-01-02", date_to="2024-01-02"))
        lazy_values = [(r.key, r.value) for r in lazy_response.results]

        assert lazy_values == raw_values, f"forward-only pad parity broken: raw={raw_values}, lazy={lazy_values}"

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

    @unittest.skip(
        "Flaky on CI since #59075 — same intermittent empty-result pattern as the other "
        "round-trip tests in this file. Root cause under investigation."
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_recomputation_picks_up_late_events_changing_bounce_and_duration(self):
        # After a late event arrives, the next precompute run (cache invalidated
        # via job deletion = simulated TTL expiry) must reflect the new
        # session-level state:
        #   • bounce flips from 1.0 → 0.0 when a second pageview lands
        #   • session_duration grows from 0 → non-zero
        #   • views grows from 1 → 2
        # The stale precomputed row stays in ClickHouse with the old job_id;
        # the new read passes the new job_id, so ReplacingMergeTree partitioning
        # by job_id naturally isolates the runs.
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

        with self._enable_lazy():
            first_resp = self._run(self._build_query(date_from="2024-01-02", date_to="2024-01-02"))
            first_metrics = {r.key: r.value for r in first_resp.results}
            first_job_ids = set(PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("id", flat=True))

            assert first_job_ids, "first run should have created at least one precompute job"

            # Stale-state sanity: single pageview = bounce (100%), zero duration.
            assert first_metrics["bounce rate"] == 100.0, f"first run bounce rate should be 100.0%, got {first_metrics}"
            assert first_metrics["views"] == 1.0, f"first run views should be 1, got {first_metrics}"

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

            # Invalidate the cache by deleting the READY job rows. This
            # simulates TTL expiry; the next ensure_precomputed cycle will
            # create fresh job_ids and re-INSERT with the updated session
            # aggregates.
            PreaggregationJob.objects.filter(id__in=first_job_ids).delete()

            second_resp = self._run(self._build_query(date_from="2024-01-02", date_to="2024-01-02"))
            second_metrics = {r.key: r.value for r in second_resp.results}
            second_job_ids = set(PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("id", flat=True))

            assert second_job_ids, "second run should have created new precompute jobs after invalidation"
            assert second_job_ids.isdisjoint(first_job_ids), (
                "recomputation should produce fresh job_ids, not reuse deleted ones"
            )

        # Recomputed state must reflect the late event.
        assert second_metrics["views"] == 2.0, f"recomputed views should be 2, got {second_metrics}"
        assert second_metrics["bounce rate"] == 0.0, (
            f"recomputed bounce rate should flip to 0.0% after second pageview, got {second_metrics}"
        )
        assert second_metrics["session duration"] is not None and second_metrics["session duration"] > 0, (
            f"recomputed session duration should be > 0, got {second_metrics}"
        )

        # Cross-check parity vs the raw events path after the late event.
        raw_resp = self._run(self._build_query(date_from="2024-01-02", date_to="2024-01-02"))
        raw_metrics = {r.key: r.value for r in raw_resp.results}
        for metric in ("views", "bounce rate", "session duration", "visitors", "sessions"):
            assert second_metrics[metric] == raw_metrics[metric], (
                f"recomputed lazy != raw for {metric}: lazy={second_metrics[metric]}, raw={raw_metrics[metric]}"
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
