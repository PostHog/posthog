import uuid
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import AttributionMode, BaseMathType, ConversionGoalFilter1

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
    TRUNCATE_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL,
)
from posthog.clickhouse.preaggregation.marketing_conversions_sql import (
    SHARDED_MARKETING_CONVERSIONS_TABLE,
    TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL,
)
from posthog.clickhouse.preaggregation.marketing_touchpoints_sql import (
    SHARDED_MARKETING_TOUCHPOINTS_TABLE,
    TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL,
)

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    ensure_precomputed,
)
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import (
    ConversionGoalProcessor,
    build_touchpoints_precompute_query,
)
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig

DATE_FROM = datetime(2025, 1, 1, tzinfo=UTC)
DATE_TO = datetime(2025, 1, 31, tzinfo=UTC)


@override_settings(IN_UNIT_TESTING=True)
class TestConversionGoalPrecomputeDedup(ClickhouseTestMixin, APIBaseTest):
    """Regression coverage for the job_id double-counting bug.

    The preagg tables are ReplacingMergeTree keyed on (team_id, job_id, person_id, *_timestamp). Because
    job_id is in the dedup key, the same physical touchpoint/conversion materialized under several job_ids
    (overlapping windows, compare-period, TTL re-materialization) survives as distinct rows even with FINAL.
    The read path groupArrays across all those job_ids, so without a read-side dedup the touchpoint arrays
    inflate and each conversion is over-credited. These tests force that duplication and assert the
    precompute path still matches the events-scan fallback exactly.
    """

    def setUp(self):
        super().setUp()
        self._clean()

    def tearDown(self):
        self._clean()
        super().tearDown()

    def _clean(self):
        sync_execute(TRUNCATE_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL())
        sync_execute(TRUNCATE_MARKETING_TOUCHPOINTS_TABLE_SQL())
        sync_execute(TRUNCATE_MARKETING_CONVERSIONS_TABLE_SQL())
        PreaggregationJob.objects.all().delete()

    def _seed_events(self):
        for distinct_id in ("user_a", "user_b", "user_c", "user_d"):
            _create_person(distinct_ids=[distinct_id], team=self.team)

        # user_a: 3 distinct campaigns then a conversion — the multi-touch case that inflates most.
        for day, (campaign, source) in [(3, ("spring", "google")), (6, ("summer", "facebook")), (9, ("fall", "bing"))]:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_a",
                timestamp=datetime(2025, 1, day, 10, tzinfo=UTC),
                properties={"utm_campaign": campaign, "utm_source": source, "utm_medium": "cpc"},
            )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_a",
            timestamp=datetime(2025, 1, 12, 10, tzinfo=UTC),
            properties={"value": 100},
        )

        # user_b: same (campaign, source) twice → single touchpoint key, two pageviews.
        for day in (4, 8):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user_b",
                timestamp=datetime(2025, 1, day, 10, tzinfo=UTC),
                properties={"utm_campaign": "winter", "utm_source": "twitter", "utm_medium": "social"},
            )
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_b",
            timestamp=datetime(2025, 1, 11, 10, tzinfo=UTC),
            properties={"value": 50},
        )

        # user_c: 1 touchpoint, 2 conversions at different times (each gets its own attribution).
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_c",
            timestamp=datetime(2025, 1, 2, 10, tzinfo=UTC),
            properties={"utm_campaign": "newyear", "utm_source": "google", "utm_medium": "cpc"},
        )
        for day in (7, 15):
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id="user_c",
                timestamp=datetime(2025, 1, day, 10, tzinfo=UTC),
                properties={"value": 30},
            )

        # user_d: conversion with no touchpoint (organic).
        _create_event(
            team=self.team,
            event="purchase",
            distinct_id="user_d",
            timestamp=datetime(2025, 1, 14, 10, tzinfo=UTC),
            properties={"value": 10},
        )

        flush_persons_and_events()

    def _make_processor(self, *, precompute: bool, attribution_mode: AttributionMode) -> ConversionGoalProcessor:
        goal = ConversionGoalFilter1(
            kind="EventsNode",
            event="purchase",
            conversion_goal_id="goal_dedup",
            conversion_goal_name="Dedup Goal",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
            properties=[],
        )
        config = MarketingAnalyticsConfig()
        config.attribution_window_days = 30
        config.attribution_mode = attribution_mode
        config.conversion_goal_precomputation_enabled = precompute
        return ConversionGoalProcessor(goal=goal, index=0, team=self.team, config=config)

    def _execute(self, query: ast.SelectQuery) -> list[tuple]:
        return execute_hogql_query(query, team=self.team).results or []

    def _materialize(self, processor: ConversionGoalProcessor) -> None:
        # Span the same range the read path will request (date_from - window .. date_to) so the
        # materialized rows cover every seeded event.
        ensure_precomputed(
            team=self.team,
            insert_query=build_touchpoints_precompute_query(),
            time_range_start=DATE_FROM,
            time_range_end=DATE_TO,
            ttl_seconds=3600,
            table=LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED,
        )
        ensure_precomputed(
            team=self.team,
            insert_query=processor.build_conversions_precompute_query(),
            time_range_start=DATE_FROM,
            time_range_end=DATE_TO,
            ttl_seconds=3600,
            table=LazyComputationTable.MARKETING_CONVERSIONS_PREAGGREGATED,
        )

    def _duplicate_under_new_job_id(self, sharded_table: str, copies: int) -> None:
        """Re-stamp every existing row for this team under a fresh job_id `copies` times.

        This faithfully mimics what the framework produces when the same window is re-materialized
        (overlapping ranges, compare-period, TTL refresh): physically identical rows under different
        job_ids that the ReplacingMergeTree dedup key cannot collapse because job_id is part of it.

        Reads the rows back into Python and re-inserts them with a new job_id (column index 1), avoiding
        any reliance on Distributed self-reads or column-order assumptions.
        """
        column_names = [
            r[0]
            for r in sync_execute(
                "SELECT name FROM system.columns WHERE table = %(table)s AND database = currentDatabase() ORDER BY position",
                {"table": sharded_table.split(".")[-1]},
            )
        ]
        job_id_idx = column_names.index("job_id")

        original_rows = sync_execute(  # nosemgrep: clickhouse-fstring-param-audit — test helper; sharded_table is a hardcoded preagg table, column_names come from system.columns, team_id parameterized
            f"SELECT {', '.join(column_names)} FROM {sharded_table} WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )
        for _ in range(copies):
            new_job_id = uuid.uuid4()
            new_rows = []
            for row in original_rows:
                row_list = list(row)
                row_list[job_id_idx] = new_job_id
                new_rows.append(tuple(row_list))
            sync_execute(  # nosemgrep: clickhouse-fstring-param-audit — test helper; sharded_table + column_names (from system.columns) are not user input
                f"INSERT INTO {sharded_table} ({', '.join(column_names)}) VALUES",
                new_rows,
            )

    def _count_and_unique(self, distributed_table: str, ts_column: str) -> tuple[int, int]:
        rows = sync_execute(  # nosemgrep: clickhouse-fstring-param-audit — test helper; distributed_table + ts_column are hardcoded preagg identifiers, team_id parameterized
            f"""
            SELECT count(), uniqExact((person_id, {ts_column}))
            FROM {distributed_table}
            WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk},
        )
        return rows[0][0], rows[0][1]

    @parameterized.expand(
        [
            (AttributionMode.LAST_TOUCH,),
            (AttributionMode.FIRST_TOUCH,),
            (AttributionMode.LINEAR,),
            (AttributionMode.TIME_DECAY,),
            (AttributionMode.POSITION_BASED,),
        ]
    )
    def test_precompute_with_duplicated_job_ids_matches_fallback(self, attribution_mode: AttributionMode):
        self._seed_events()

        preagg_processor = self._make_processor(precompute=True, attribution_mode=attribution_mode)
        self._materialize(preagg_processor)

        touchpoints_table = SHARDED_MARKETING_TOUCHPOINTS_TABLE()
        conversions_table = SHARDED_MARKETING_CONVERSIONS_TABLE()

        # Force the duplication: every materialized row now also exists under 2 extra job_ids (3x total).
        self._duplicate_under_new_job_id(touchpoints_table, copies=2)
        self._duplicate_under_new_job_id(conversions_table, copies=2)

        # Sanity: the raw table really is duplicated (count() far exceeds unique (person, timestamp)).
        tp_count, tp_unique = self._count_and_unique(touchpoints_table, "touchpoint_timestamp")
        cv_count, cv_unique = self._count_and_unique(conversions_table, "conversion_timestamp")
        assert tp_count == tp_unique * 3, f"expected 3x touchpoint duplication, got {tp_count} vs {tp_unique}"
        assert cv_count == cv_unique * 3, f"expected 3x conversion duplication, got {cv_count} vs {cv_unique}"

        fallback_rows = sorted(
            self._execute(
                self._make_processor(precompute=False, attribution_mode=attribution_mode).generate_cte_query(
                    additional_conditions=[]
                )
            )
        )
        preagg_rows = sorted(
            self._execute(
                preagg_processor.generate_cte_query(additional_conditions=[], date_from=DATE_FROM, date_to=DATE_TO)
            )
        )

        # The fix: read-side dedup collapses the job_id duplicates, so attribution matches ground truth
        # despite the table holding 3x the rows.
        assert _round_rows(preagg_rows) == _round_rows(fallback_rows), (
            f"{attribution_mode}: duplicated job_ids inflated the precompute result.\n"
            f"fallback: {fallback_rows}\npreagg: {preagg_rows}"
        )

    def test_duplicated_job_ids_would_inflate_without_dedup(self):
        """Pins the bug: prove that summing the duplicated rows naively (no dedup) yields an inflated
        conversion total, while the deduped read path returns the ground-truth total. This is what makes
        the equivalence test above meaningful — without the fix the numbers genuinely diverge.
        """
        self._seed_events()

        attribution_mode = AttributionMode.LAST_TOUCH
        preagg_processor = self._make_processor(precompute=True, attribution_mode=attribution_mode)
        self._materialize(preagg_processor)

        conversions_table = SHARDED_MARKETING_CONVERSIONS_TABLE()
        conversion_rows_before_dup = sync_execute(
            f"SELECT count() FROM {conversions_table} WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )[0][0]
        self._duplicate_under_new_job_id(conversions_table, copies=2)
        self._duplicate_under_new_job_id(SHARDED_MARKETING_TOUCHPOINTS_TABLE(), copies=2)

        # Ground-truth conversion count from the events scan.
        fallback_rows = self._execute(
            self._make_processor(precompute=False, attribution_mode=attribution_mode).generate_cte_query(
                additional_conditions=[]
            )
        )
        ground_truth_conversions = sum(_conversions_in_row(r) for r in fallback_rows)

        # Naive (buggy) count: every duplicated conversion row counted once → 3x inflation.
        raw_conversion_rows = sync_execute(
            f"SELECT count() FROM {conversions_table} WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )[0][0]
        assert raw_conversion_rows == conversion_rows_before_dup * 3, (
            "test setup must produce 3x raw duplication to demonstrate the inflation it guards against"
        )

        # Deduped read path: matches ground truth, not the inflated raw count.
        preagg_rows = self._execute(
            preagg_processor.generate_cte_query(additional_conditions=[], date_from=DATE_FROM, date_to=DATE_TO)
        )
        deduped_conversions = sum(_conversions_in_row(r) for r in preagg_rows)
        assert deduped_conversions == ground_truth_conversions, (
            f"dedup failed: precompute reported {deduped_conversions} conversions vs ground truth "
            f"{ground_truth_conversions} (raw rows: {raw_conversion_rows})"
        )


def _round_rows(rows: list[tuple]) -> list[tuple]:
    return [tuple(round(v, 6) if isinstance(v, float) else v for v in row) for row in rows]


def _conversions_in_row(row: tuple) -> float:
    """Sum the numeric columns of a CTE result row, ignoring the UTM key strings. This equals the
    conversion count only under math=TOTAL (each event contributes 1.0), which is what this suite uses;
    it's only compared like-for-like (deduped vs fallback, both attributed) so the math cancels out.
    """
    return sum(v for v in row if isinstance(v, (int, float)) and not isinstance(v, bool))
