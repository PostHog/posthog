from datetime import UTC, datetime, timedelta

import unittest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from django.test import override_settings

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    find_missing_contiguous_windows,
    parse_ttl_schedule,
    split_ranges_by_ttl,
)
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    BOUNCES_INSERT_TEMPLATE,
    DIMENSIONAL_TTL_SECONDS,
    STATS_INSERT_TEMPLATE,
    _base_placeholders,
    ensure_web_bounces_dimensional_precomputed,
    ensure_web_stats_dimensional_precomputed,
)

WINDOW_START = datetime(2024, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2024, 1, 8, tzinfo=UTC)


@override_settings(IN_UNIT_TESTING=True)
class TestWebDimensionalPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        # Rows are born expired against the real CH clock (expires_at derives from
        # the frozen test clock), so stop TTL merges to keep parts between INSERT
        # and read — same guard the lazy precompute tests use.
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_stats_dimensional_preaggregated")
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_bounces_dimensional_preaggregated")

    def _seed_two_sessions(self) -> None:
        # p1: two pageviews on example.com in one session. p2: one pageview on other.com.
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

    def _job_ids_tuple(self, result) -> str:
        return "(" + ", ".join(f"'{jid}'" for jid in result.job_ids) + ")"

    def _read_stats_totals(self, result) -> tuple[int, int, int]:
        rows = sync_execute(
            f"""
            SELECT
                uniqMerge(persons_uniq_state),
                uniqMerge(sessions_uniq_state),
                sumMerge(pageviews_count_state)
            FROM web_stats_dimensional_preaggregated
            WHERE team_id = %(team_id)s AND job_id IN {self._job_ids_tuple(result)}
            """,
            {"team_id": self.team.pk},
        )
        return int(rows[0][0]), int(rows[0][1]), int(rows[0][2])

    @freeze_time("2024-01-15T12:00:00Z")
    def test_stats_ensure_creates_jobs_and_correct_totals(self):
        self._seed_two_sessions()
        result = ensure_web_stats_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)

        assert result.ready
        assert len(result.job_ids) > 0
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == len(result.job_ids)

        persons, sessions, pageviews = self._read_stats_totals(result)
        assert persons == 2
        assert sessions == 2
        assert pageviews == 3

    @freeze_time("2024-01-15T12:00:00Z")
    def test_stats_breaks_down_by_host(self):
        self._seed_two_sessions()
        result = ensure_web_stats_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)

        rows = sync_execute(
            f"""
            SELECT
                host,
                uniqMerge(persons_uniq_state) AS persons,
                uniqMerge(sessions_uniq_state) AS sessions,
                sumMerge(pageviews_count_state) AS pageviews
            FROM web_stats_dimensional_preaggregated
            WHERE team_id = %(team_id)s AND job_id IN {self._job_ids_tuple(result)}
            GROUP BY host
            ORDER BY host
            """,
            {"team_id": self.team.pk},
        )
        by_host = {row[0]: (int(row[1]), int(row[2]), int(row[3])) for row in rows}
        assert by_host["example.com"] == (1, 1, 2)
        assert by_host["other.com"] == (1, 1, 1)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_stats_second_call_is_cache_hit(self):
        self._seed_two_sessions()
        first = ensure_web_stats_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)
        jobs_after_first = PreaggregationJob.objects.filter(team_id=self.team.pk).count()

        second = ensure_web_stats_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)
        jobs_after_second = PreaggregationJob.objects.filter(team_id=self.team.pk).count()

        assert second.ready
        # No new jobs created — the window is already fresh.
        assert jobs_after_second == jobs_after_first
        assert set(second.job_ids) == set(first.job_ids)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_bounces_ensure_creates_jobs_and_correct_totals(self):
        self._seed_two_sessions()
        result = ensure_web_bounces_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)

        assert result.ready
        assert len(result.job_ids) > 0

        rows = sync_execute(
            f"""
            SELECT
                uniqMerge(persons_uniq_state),
                uniqMerge(sessions_uniq_state),
                sumMerge(pageviews_count_state),
                sumMerge(bounces_count_state),
                sumMerge(total_session_count_state)
            FROM web_bounces_dimensional_preaggregated
            WHERE team_id = %(team_id)s AND job_id IN {self._job_ids_tuple(result)}
            """,
            {"team_id": self.team.pk},
        )
        persons, sessions, pageviews, bounces, total_sessions = (int(v) for v in rows[0])
        assert persons == 2
        assert sessions == 2
        assert pageviews == 3
        assert total_sessions == 2
        # Bounce semantics depend on the session table; just assert it's in range.
        assert 0 <= bounces <= 2

    @freeze_time("2024-01-15T12:00:00Z")
    def test_separate_chunks_share_one_query_hash_and_read_reassembles_window(self):
        # Two events in two different 7-day chunks of the same window.
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-03T10:00:00Z",  # older chunk
            properties={"$session_id": str(uuid7("2024-01-03")), "$host": "example.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2024-01-10T10:00:00Z",  # newer chunk
            properties={"$session_id": str(uuid7("2024-01-10")), "$host": "example.com"},
        )

        chunk_older = ensure_web_stats_dimensional_precomputed(
            self.team, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 8, tzinfo=UTC)
        )
        chunk_newer = ensure_web_stats_dimensional_precomputed(
            self.team, datetime(2024, 1, 8, tzinfo=UTC), datetime(2024, 1, 15, tzinfo=UTC)
        )
        assert chunk_older.ready and chunk_newer.ready

        # 1. Every chunk shares ONE cache key (time range is excluded from the hash).
        distinct_hashes = PreaggregationJob.objects.filter(team_id=self.team.pk).values("query_hash").distinct()
        assert distinct_hashes.count() == 1

        # 2/3. A read over the union of all chunk job_ids reassembles the full window.
        all_ids = "(" + ", ".join(f"'{jid}'" for jid in [*chunk_older.job_ids, *chunk_newer.job_ids]) + ")"
        rows = sync_execute(
            f"""
            SELECT uniqMerge(persons_uniq_state), uniqMerge(sessions_uniq_state), sumMerge(pageviews_count_state)
            FROM web_stats_dimensional_preaggregated
            WHERE team_id = %(team_id)s AND job_id IN {all_ids}
            """,
            {"team_id": self.team.pk},
        )
        persons, sessions, pageviews = (int(v) for v in rows[0])
        assert (persons, sessions, pageviews) == (2, 2, 2)  # one event in each chunk, merged


class TestWebDimensionalPrecomputeTemplates(unittest.TestCase):
    """Pure HogQL-parse checks — no DB/ClickHouse, so they validate the templates
    even without a running stack."""

    def _placeholders(self) -> dict[str, ast.Expr]:
        # Mirror what ensure_precomputed supplies: caller placeholders plus the
        # framework-managed time window sentinels.
        return {
            **_base_placeholders(),
            "time_window_min": ast.Constant(value="__MIN__"),
            "time_window_max": ast.Constant(value="__MAX__"),
        }

    def test_templates_parse_and_alias_every_top_level_column(self):
        # The framework requires every top-level SELECT expression to be aliased
        # (it derives the INSERT column list from the aliases), and the only
        # unbound placeholders may be time_window_min/max.
        for template in (STATS_INSERT_TEMPLATE, BOUNCES_INSERT_TEMPLATE):
            query = parse_select(template, placeholders=self._placeholders())
            assert isinstance(query, ast.SelectQuery)
            assert query.select
            assert all(isinstance(expr, ast.Alias) for expr in query.select)

    def test_stats_and_bounces_emit_expected_aggregate_columns(self):
        stats = parse_select(STATS_INSERT_TEMPLATE, placeholders=self._placeholders())
        bounces = parse_select(BOUNCES_INSERT_TEMPLATE, placeholders=self._placeholders())
        assert isinstance(stats, ast.SelectQuery) and isinstance(bounces, ast.SelectQuery)
        stats_aliases = {expr.alias for expr in stats.select if isinstance(expr, ast.Alias)}
        bounces_aliases = {expr.alias for expr in bounces.select if isinstance(expr, ast.Alias)}
        assert {"persons_uniq_state", "sessions_uniq_state", "pageviews_count_state"}.issubset(stats_aliases)
        assert {
            "persons_uniq_state",
            "sessions_uniq_state",
            "pageviews_count_state",
            "bounces_count_state",
            "total_session_duration_state",
            "total_session_count_state",
        }.issubset(bounces_aliases)
        # Stats is per-pathname; bounces has no pathname dimension.
        assert "pathname" in stats_aliases
        assert "pathname" not in bounces_aliases


class TestColdBackfillSplitsByTtlBandNotPerDay(unittest.TestCase):
    """A cold N-day request does NOT issue one INSERT per day.

    `find_missing_contiguous_windows` merges all missing days into a single
    contiguous range; `split_ranges_by_ttl` then cuts that range only at the
    TTL-band cutoffs. So the number of INSERTs equals the number of TTL bands the
    window spans (a handful), and the bulk of history is one big INSERT — not 90.
    """

    @freeze_time("2024-06-15T12:00:00Z")
    def test_dimensional_schedule_90d_cold_range_is_three_bands(self):
        end = datetime(2024, 6, 15, 12, tzinfo=UTC)
        start = end - timedelta(days=90)

        # Cold cache (no existing jobs) -> a single contiguous missing range.
        missing = find_missing_contiguous_windows([], start, end)
        assert len(missing) == 1

        bands = split_ranges_by_ttl(missing, parse_ttl_schedule(DIMENSIONAL_TTL_SECONDS, team_timezone="UTC"))

        # DIMENSIONAL_TTL_SECONDS has 3 entries (0d / 2d / default) -> 3 INSERTs,
        # oldest first. NOT 90.
        ttls = [ttl for _s, _e, ttl in bands]
        assert ttls == [90 * 86400, 86400, 3600]

        # The bulk of history is ONE query covering many days, not one-per-day.
        oldest_start, oldest_end, _ = bands[0]
        assert (oldest_end - oldest_start).days >= 60

        # Bands tile the window contiguously and cover the whole ~90 days.
        for (_s1, e1, _t1), (s2, _e2, _t2) in zip(bands, bands[1:]):
            assert e1 == s2
        assert sum((e - s).days for s, e, _ in bands) >= 90

    @freeze_time("2024-06-15T12:00:00Z")
    def test_today_yesterday_7d_rest_schedule_is_four_bands(self):
        # The exact schedule shape described in review: today / yesterday / last
        # 7 days / the rest -> four INSERTs for a cold 90-day range.
        end = datetime(2024, 6, 15, 12, tzinfo=UTC)
        start = end - timedelta(days=90)
        schedule = parse_ttl_schedule(
            {"0d": 15 * 60, "1d": 60 * 60, "7d": 24 * 60 * 60, "default": 7 * 24 * 60 * 60},
            team_timezone="UTC",
        )
        bands = split_ranges_by_ttl(find_missing_contiguous_windows([], start, end), schedule)
        assert len(bands) == 4
