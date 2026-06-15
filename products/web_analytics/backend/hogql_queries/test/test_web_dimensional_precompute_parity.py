"""Parity tests: the precomputation-framework dimensional tables must produce the
same aggregates as the v2 pre-aggregation tables for the same events.

The v2 INSERT (`WEB_STATS_INSERT_SQL` / `WEB_BOUNCES_INSERT_SQL`) is hand-written
ClickHouse over the physical `raw_sessions` table and materialized event columns;
the new path is HogQL over `events`+`sessions` driven by `ensure_precomputed`.
We run both over the same seeded window and compare.

Metrics are event-derived and must match exactly. We compare metrics grouped by
the dimensions both paths source identically (see the dimension-list comment
below for what is and isn't comparable, and why), which is the guarantee these
tables exist to provide.
"""

from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL, WEB_STATS_INSERT_SQL

from products.web_analytics.backend.hogql_queries.test.web_preaggregated_test_base import (
    WebAnalyticsPreAggregatedTestBase,
)
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    ensure_web_bounces_dimensional_precomputed,
    ensure_web_stats_dimensional_precomputed,
)

DATE_START = "2024-01-01"
DATE_END = "2024-01-02"
WINDOW_START = datetime(2024, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2024, 1, 2, tzinfo=UTC)

# Dimensions compared against v2. The comparison is restricted to dimensions both
# paths source identically for a given table:
#   - `pathname` is excluded everywhere: v2 reads the materialized `mat_$pathname`,
#     whose backfill is unreliable in the test harness (existing v2 tests never
#     assert values), whereas the new path reads `properties.$pathname`. The new
#     table's pathname breakdown is asserted separately. (Bounces have no pathname.)
#   - geoip (country/city/region) is compared for stats (v2 sources it from the
#     event's `mat_$geoip_*`, same as the new path) but excluded for bounces, where
#     v2 sources it from the session's initial geoip (empty in the harness) while
#     the new path uses event geoip.
_DEVICE_DIMS = ["host", "device_type", "browser", "os", "viewport_width", "viewport_height"]
_GEOIP_DIMS = ["country_code", "city_name", "region_code"]
STATS_COMPARABLE_DIMS = [*_DEVICE_DIMS, *_GEOIP_DIMS]
BOUNCES_COMPARABLE_DIMS = _DEVICE_DIMS


class TestWebDimensionalPrecomputeParity(WebAnalyticsPreAggregatedTestBase):
    def setUp(self):
        super().setUp()
        # Born-expired rows vs the real CH clock — keep parts between INSERT and read.
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_stats_dimensional_preaggregated")
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_bounces_dimensional_preaggregated")

    def _pageview(self, distinct_id: str, session: str, ts: str, **props) -> None:
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=ts,
            properties={"$session_id": session, **props},
        )

    def _setup_test_data(self):
        sa, sb, sc = (str(uuid7(DATE_START)) for _ in range(3))
        with freeze_time("2024-01-01T09:00:00Z"):
            # Create persons so events resolve to a stable person_id per distinct_id
            # (without this, _create_event assigns a fresh random person_id per row).
            for did in ("user_a", "user_b", "user_c"):
                _create_person(team_id=self.team.pk, distinct_ids=[did])
            # user_a: non-bounce session, two pathnames on app.example.com.
            desktop_us = {
                "$host": "app.example.com",
                "$device_type": "Desktop",
                "$browser": "Chrome",
                "$os": "Windows",
                "$viewport_width": 1920,
                "$viewport_height": 1080,
                "$geoip_country_code": "US",
                "$geoip_city_name": "New York",
                "$geoip_subdivision_1_code": "NY",
            }
            self._pageview("user_a", sa, "2024-01-01T10:00:00Z", **{**desktop_us, "$pathname": "/"})
            self._pageview("user_a", sa, "2024-01-01T10:03:00Z", **{**desktop_us, "$pathname": "/pricing"})
            # user_b: single-pageview (bounce) on app.example.com, mobile.
            self._pageview(
                "user_b",
                sb,
                "2024-01-01T11:00:00Z",
                **{
                    "$host": "app.example.com",
                    "$device_type": "Mobile",
                    "$browser": "Safari",
                    "$os": "iOS",
                    "$viewport_width": 390,
                    "$viewport_height": 844,
                    "$geoip_country_code": "US",
                    "$geoip_city_name": "San Francisco",
                    "$geoip_subdivision_1_code": "CA",
                    "$pathname": "/",
                },
            )
            # user_c: single pageview on blog.example.com, different geo.
            self._pageview(
                "user_c",
                sc,
                "2024-01-01T12:00:00Z",
                **{
                    "$host": "blog.example.com",
                    "$device_type": "Desktop",
                    "$browser": "Firefox",
                    "$os": "Linux",
                    "$viewport_width": 1280,
                    "$viewport_height": 720,
                    "$geoip_country_code": "GB",
                    "$geoip_city_name": "London",
                    "$geoip_subdivision_1_code": "ENG",
                    "$pathname": "/blog",
                },
            )

    def _job_ids_tuple(self, result) -> str:
        return "(" + ", ".join(f"'{jid}'" for jid in result.job_ids) + ")"

    def _read_breakdown(self, table: str, metrics: str, dims: list[str], job_filter: str = "") -> dict:
        dim_sql = ", ".join(dims)
        rows = sync_execute(
            f"""
            SELECT {dim_sql}, {metrics}
            FROM {table}
            WHERE team_id = %(team_id)s {job_filter}
            GROUP BY {dim_sql}
            """,
            {"team_id": self.team.pk},
        )
        n = len(dims)
        return {tuple(row[:n]): tuple(int(v) for v in row[n:]) for row in rows}

    @freeze_time("2024-01-15T12:00:00Z")
    def test_stats_parity_with_v2(self):
        # v2 path: populate web_pre_aggregated_stats directly.
        sync_execute(
            WEB_STATS_INSERT_SQL(
                date_start=DATE_START,
                date_end=DATE_END,
                team_ids=[self.team.pk],
                table_name="web_pre_aggregated_stats",
            )
        )
        # new path: precomputation framework into the dimensional table.
        result = ensure_web_stats_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)

        metrics = "uniqMerge(persons_uniq_state), uniqMerge(sessions_uniq_state), sumMerge(pageviews_count_state)"
        job_filter = f"AND job_id IN {self._job_ids_tuple(result)}"
        v2 = self._read_breakdown("web_pre_aggregated_stats", metrics, STATS_COMPARABLE_DIMS)
        new = self._read_breakdown(
            "web_stats_dimensional_preaggregated", metrics, STATS_COMPARABLE_DIMS, job_filter=job_filter
        )

        assert new == v2, f"stats breakdown mismatch\nv2={v2}\nnew={new}"
        # Seed sanity: no person/session spans hosts, so per-host sums add up to
        # 3 persons, 3 sessions, 4 pageviews overall.
        totals = tuple(sum(v[i] for v in new.values()) for i in range(3))
        assert totals == (3, 3, 4), totals

        # The new table breaks down by pathname (read from properties, not a
        # materialized column) — validate that independently of v2.
        by_path = self._read_breakdown(
            "web_stats_dimensional_preaggregated",
            "sumMerge(pageviews_count_state)",
            ["pathname"],
            job_filter=job_filter,
        )
        assert by_path == {("/",): (2,), ("/pricing",): (1,), ("/blog",): (1,)}, by_path

    @freeze_time("2024-01-15T12:00:00Z")
    def test_bounces_parity_with_v2(self):
        sync_execute(
            WEB_BOUNCES_INSERT_SQL(
                date_start=DATE_START,
                date_end=DATE_END,
                team_ids=[self.team.pk],
                table_name="web_pre_aggregated_bounces",
            )
        )
        result = ensure_web_bounces_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)

        # Event-derived / deterministic metrics must match exactly.
        metrics = (
            "uniqMerge(persons_uniq_state), uniqMerge(sessions_uniq_state), "
            "sumMerge(pageviews_count_state), sumMerge(total_session_count_state)"
        )
        v2 = self._read_breakdown("web_pre_aggregated_bounces", metrics, BOUNCES_COMPARABLE_DIMS)
        new = self._read_breakdown(
            "web_bounces_dimensional_preaggregated",
            metrics,
            BOUNCES_COMPARABLE_DIMS,
            job_filter=f"AND job_id IN {self._job_ids_tuple(result)}",
        )
        assert new == v2, f"bounces breakdown mismatch\nv2={v2}\nnew={new}"

        # Bounce + duration are session-derived; compare grand totals (each path
        # reads its own session table, but for this seed they should agree).
        bounce_metrics = "sumMerge(bounces_count_state), sumMerge(total_session_duration_state)"
        v2_tot = sync_execute(
            f"SELECT {bounce_metrics} FROM web_pre_aggregated_bounces WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )[0]
        new_tot = sync_execute(
            f"SELECT {bounce_metrics} FROM web_bounces_dimensional_preaggregated "
            f"WHERE team_id = %(team_id)s AND job_id IN {self._job_ids_tuple(result)}",
            {"team_id": self.team.pk},
        )[0]
        assert int(new_tot[0]) == int(v2_tot[0]), f"bounce count mismatch v2={v2_tot[0]} new={new_tot[0]}"
        assert int(new_tot[1]) == int(v2_tot[1]), f"duration mismatch v2={v2_tot[1]} new={new_tot[1]}"
