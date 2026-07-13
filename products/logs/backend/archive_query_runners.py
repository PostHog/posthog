import datetime as dt
from typing import cast

from posthog.schema import PropertyOperator

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr

from posthog.models.filters.mixins.utils import cached_property

from products.logs.backend.log_attributes_query_runner import LogAttributesQueryRunner
from products.logs.backend.log_facet_values_query_runner import DEFAULT_FACET_LIMIT, LogFacetValuesQueryRunner
from products.logs.backend.log_values_query_runner import LogValuesQueryRunner
from products.logs.backend.logs_query_runner import LogsFilterBuilder, LogsQueryRunner, ilike_pattern
from products.logs.backend.sparkline_query_runner import BREAKDOWN_DB_FIELD, DEFAULT_BREAKDOWN, SparklineQueryRunner

# Archive queries scan Iceberg parquet on S3 without skip indexes or projections, so they get
# a longer execution budget than hot queries but a hard bytes ceiling so a broad scan fails
# legibly instead of running away.
ARCHIVE_MAX_EXECUTION_SECONDS = 120
ARCHIVE_MAX_READ_BYTES = 50_000_000_000

ARCHIVE_SPARKLINE_MAX_READ_BYTES = 25_000_000_000

# Attribute autocomplete aggregates over the raw attribute maps (no pre-aggregated
# log_attributes table exists for the archive), so allow more bytes than the hot 5GB cap
# but keep "break" semantics: partial autocomplete results beat errors.
ARCHIVE_ATTRIBUTES_MAX_EXECUTION_SECONDS = 60
ARCHIVE_ATTRIBUTES_MAX_READ_BYTES = 20_000_000_000


class ArchiveLogsFilterBuilder(LogsFilterBuilder):
    # logs_archive has a single Map(String, String) attributes column; the hot table's
    # __str/__float typed-map suffixes resolve via property-groups config keyed to
    # logs_distributed and would silently match nothing here.
    TYPED_ATTRIBUTE_MAPS = False

    def _partition_pruning_exprs(self) -> list[ast.Expr]:
        # The Iceberg partition spec is (team_id, log_date); team_id comes from the printer's
        # guard, log_date bounds here prune partitions.
        return [
            parse_expr(
                "log_date >= toDate({date_from}) and log_date <= toDate({date_to})",
                placeholders={
                    **self.query_date_range.to_placeholders(),
                },
            )
        ]

    def _cursor_partition_pruning_expr(self, ts_op: str, cursor_ts: dt.datetime) -> ast.Expr:
        return parse_expr(
            f"log_date {ts_op} toDate({{cursor_ts}})",
            placeholders={"cursor_ts": ast.Constant(value=cursor_ts)},
        )

    def resource_filter(self, *, existing_filters):
        # No log_attributes rollup exists for the archive, so instead of the hot path's
        # fingerprint subqueries we filter the resource_attributes map directly. The hot
        # semantics (resource matches ALL positive filters, is excluded by ANY negative one)
        # reduce to a plain AND of row-level predicates because each row carries its resource.
        exprs: list[ast.Expr] = []
        for resource_attribute_filter in [
            *self.resource_attribute_filters,
            *self.resource_attribute_negative_filters,
        ]:
            # Map subscripts return '' for absent keys, never NULL, so property_to_expr's
            # IS_SET/IS_NOT_SET (!= NULL / = NULL) would be constant, so use mapContains.
            if resource_attribute_filter.operator == PropertyOperator.IS_SET:
                exprs.append(
                    parse_expr(
                        "mapContains(resource_attributes, {key})",
                        placeholders={"key": ast.Constant(value=resource_attribute_filter.key)},
                    )
                )
            elif resource_attribute_filter.operator == PropertyOperator.IS_NOT_SET:
                exprs.append(
                    parse_expr(
                        "not mapContains(resource_attributes, {key})",
                        placeholders={"key": ast.Constant(value=resource_attribute_filter.key)},
                    )
                )
            else:
                exprs.append(property_to_expr(resource_attribute_filter.copy(deep=True), team=self.team))

        if not exprs:
            return ast.Constant(value=1)
        return ast.And(exprs=exprs)


class ArchivedLogsQueryRunner(LogsQueryRunner):
    LOGS_TABLE = "posthog.logs_archive"
    FILTER_BUILDER_CLASS = ArchiveLogsFilterBuilder

    def _live_logs_checkpoint_expr(self) -> ast.Expr:
        # Live tail never routes to the archive; keep the column position stable for _calculate.
        return ast.Constant(value=None)

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return super().settings.model_copy(
            update={
                "max_execution_time": ARCHIVE_MAX_EXECUTION_SECONDS,
                "max_bytes_to_read": ARCHIVE_MAX_READ_BYTES,
                "read_overflow_mode": "throw",
            }
        )


class ArchivedSparklineQueryRunner(SparklineQueryRunner):
    LOGS_TABLE = "posthog.logs_archive"
    FILTER_BUILDER_CLASS = ArchiveLogsFilterBuilder

    def _live_logs_checkpoint_expr(self) -> ast.Expr:
        return ast.Constant(value=None)

    def _time_field_expr(self) -> ast.Expr:
        # No minute-aggregate projection on the archive; the toStartOfMinute trick would only
        # obscure the predicate.
        return ast.Field(chain=["timestamp"])

    def _bytes_expr(self) -> ast.Expr:
        # The archive doesn't store uncompressed byte counts.
        return parse_expr("0")

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return super().settings.model_copy(
            update={
                "max_bytes_to_read": ARCHIVE_SPARKLINE_MAX_READ_BYTES,
                "read_overflow_mode": "throw",
            }
        )

    def _can_use_preagg(self) -> bool:
        """logs_archive_sparkline only has service/severity/resource dims, so any body search
        or attribute filter forces a raw scan of logs_archive."""
        if self.query.searchTerm:
            return False
        if self.query.filterGroup and any(len(group.values or []) > 0 for group in self.query.filterGroup.values):
            return False
        return self.query_date_range.interval_name != "second"

    def _preagg_where(self) -> ast.Expr:
        exprs: list[ast.Expr] = [
            parse_expr(
                "log_date >= toDate({date_from}) and log_date <= toDate({date_to})",
                placeholders={**self.query_date_range.to_placeholders()},
            ),
            parse_expr(
                "time_minute >= {date_from} and time_minute <= {date_to}",
                placeholders={**self.query_date_range.to_placeholders()},
            ),
        ]
        if self.query.serviceNames:
            exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )
        if self.query.severityLevels:
            exprs.append(
                parse_expr(
                    "severity_text IN {severityLevels}",
                    placeholders={
                        "severityLevels": ast.Tuple(
                            exprs=[ast.Constant(value=str(sl)) for sl in self.query.severityLevels]
                        )
                    },
                )
            )
        if self.query.resourceFingerprint:
            exprs.append(
                parse_expr(
                    "resource_fingerprint = {resourceFingerprint}",
                    placeholders={"resourceFingerprint": ast.Constant(value=str(self.query.resourceFingerprint))},
                )
            )
        return ast.And(exprs=exprs)

    def to_query(self) -> ast.SelectQuery:
        if not self._can_use_preagg():
            return super().to_query()

        query = parse_select(
            """
                SELECT
                    am.time_bucket AS time,
                    {breakdown_field},
                    ifNull(ac.event_count, 0) AS count,
                    ifNull(ac.bytes_uncompressed, 0) AS bytes_uncompressed
                FROM (
                    SELECT
                        dateAdd({date_from_start_of_interval}, {number_interval_period}) AS time_bucket
                    FROM numbers(
                        floor(
                            dateDiff({interval},
                                     {date_from_start_of_interval},
                                     {date_to_start_of_interval}) / {interval_count} + 1
                                    )
                        )
                    WHERE
                        time_bucket >= {date_from_start_of_interval} and
                        time_bucket <= greatest(
                            {date_from_start_of_interval},
                            toStartOfInterval({date_to} - toIntervalSecond(1), {one_interval_period})
                        )
                ) AS am
                LEFT JOIN (
                    SELECT
                        toStartOfInterval(time_minute, {one_interval_period}) AS time,
                        {breakdown_field},
                        sum(event_count) AS event_count,
                        0 AS bytes_uncompressed
                    FROM posthog.logs_archive_sparkline
                    WHERE {where}
                    GROUP BY {breakdown_field}, time
                ) AS ac ON am.time_bucket = ac.time
                ORDER BY time asc, {breakdown_field} asc
                LIMIT 1000
        """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "where": self._preagg_where(),
                "breakdown_field": ast.Field(
                    chain=[BREAKDOWN_DB_FIELD[self.query.sparklineBreakdownBy or DEFAULT_BREAKDOWN]]
                ),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query


class ArchivedLogAttributesQueryRunner(LogAttributesQueryRunner):
    FILTER_BUILDER_CLASS = ArchiveLogsFilterBuilder

    def _map_column(self) -> str:
        return "resource_attributes" if self.query.attributeType == "resource" else "attributes"

    def _archive_bounds(self) -> ast.Expr:
        return parse_expr(
            "log_date >= toDate({date_from_start_of_interval})"
            " and log_date <= toDate({date_to_start_of_interval} + {one_interval_period})"
            " and timestamp >= {date_from_start_of_interval}"
            " and timestamp <= {date_to_start_of_interval} + {one_interval_period}",
            placeholders={**self.query_date_range.to_placeholders()},
        )

    def _to_query_keys_only(self) -> ast.SelectQuery:
        query = parse_select(
            f"""
            SELECT
                groupArray({{limit}})(attribute_key) as keys,
                count() as total_count
            FROM (
                SELECT
                    attribute_key,
                    count() AS attribute_count
                FROM (
                    SELECT arrayJoin(mapKeys({self._map_column()})) AS attribute_key
                    FROM posthog.logs_archive
                    WHERE {{bounds}} AND {{where}}
                )
                WHERE attribute_key ILIKE {{search}}
                GROUP BY attribute_key
                ORDER BY lower(attribute_key) = lower({{exact}}) DESC, has(splitByNonAlpha(lower(attribute_key)), lower({{exact}})) DESC, attribute_count desc, attribute_key asc
                OFFSET {{offset}}
            )
            """,
            placeholders={
                "search": ast.Constant(value=ilike_pattern(self.query.search)),
                "exact": ast.Constant(value=self.query.search),
                "limit": ast.Constant(value=self.query.limit),
                "offset": ast.Constant(value=self.query.offset),
                "bounds": self._archive_bounds(),
                "where": self.where(),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def _to_query_with_value_search(self) -> ast.SelectQuery:
        # Same two-branch shape as the hot runner: keys whose name matches, then keys whose
        # values match but whose name does not (the NOT ILIKE dedupes across branches).
        query = parse_select(
            f"""
            SELECT
                attribute_key,
                match_type,
                sample_value,
                total_count
            FROM (
                SELECT
                    kv.1 AS attribute_key,
                    'key' AS match_type,
                    '' AS sample_value,
                    count() AS total_count
                FROM (
                    SELECT arrayJoin(mapItems({self._map_column()})) AS kv
                    FROM posthog.logs_archive
                    WHERE {{bounds}} AND {{where}}
                )
                WHERE kv.1 ILIKE {{search}}
                GROUP BY attribute_key

                UNION ALL

                SELECT
                    kv.1 AS attribute_key,
                    'value' AS match_type,
                    any(kv.2) AS sample_value,
                    count() AS total_count
                FROM (
                    SELECT arrayJoin(mapItems({self._map_column()})) AS kv
                    FROM posthog.logs_archive
                    WHERE {{bounds}} AND {{where}}
                )
                WHERE kv.2 ILIKE {{search}} AND kv.1 NOT ILIKE {{search}}
                GROUP BY attribute_key
            )
            ORDER BY
                match_type = 'key' DESC,
                lower(attribute_key) = lower({{exact}}) DESC,
                has(splitByNonAlpha(lower(attribute_key)), lower({{exact}})) DESC,
                total_count DESC,
                attribute_key ASC
            LIMIT {{limit}}
            OFFSET {{offset}}
            """,
            placeholders={
                "search": ast.Constant(value=ilike_pattern(self.query.search)),
                "exact": ast.Constant(value=self.query.search),
                "limit": ast.Constant(value=self.query.limit),
                "offset": ast.Constant(value=self.query.offset),
                "bounds": self._archive_bounds(),
                "where": self.where(),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return HogQLGlobalSettings(
            read_overflow_mode="break",
            max_bytes_to_read=ARCHIVE_ATTRIBUTES_MAX_READ_BYTES,
            max_execution_time=ARCHIVE_ATTRIBUTES_MAX_EXECUTION_SECONDS,
        )


class ArchivedLogFacetValuesQueryRunner(LogFacetValuesQueryRunner):
    # The hot resource-attribute facet reads the log_attributes rollup, which has no archive
    # equivalent. Both branches here scan logs_archive directly: column facets group the top-level
    # column, resource facets group the raw resource_attributes map (like ArchivedLogValuesQueryRunner).
    def _exact_timestamp_bounds(self) -> ast.Expr:
        return parse_expr(
            "timestamp >= {date_from} AND timestamp < {date_to}",
            placeholders={
                "date_from": ast.Constant(value=self.query_date_range.date_from()),
                "date_to": ast.Constant(value=self.query_date_range.date_to()),
            },
        )

    def _column_facet_query(self) -> ast.SelectQuery:
        facet = ast.Field(chain=[cast(str, self.facet_field)])
        filter_builder = ArchiveLogsFilterBuilder(
            self.query,
            self.team,
            self.query_date_range,
            exclude_facet_field=self.facet_field,
        )
        exprs: list[ast.Expr] = [filter_builder.where(), self._exact_timestamp_bounds()]
        if self.facet_search:
            exprs.append(
                parse_expr(
                    "{facet} ILIKE {pattern}",
                    placeholders={"facet": facet, "pattern": ast.Constant(value=ilike_pattern(self.facet_search))},
                )
            )
        query = parse_select(
            """
            SELECT {facet} AS value, count() AS count
            FROM posthog.logs_archive
            WHERE {where}
            GROUP BY {facet}
            ORDER BY count() DESC, {facet} ASC
            LIMIT {limit}
            """,
            placeholders={
                "facet": facet,
                "where": ast.And(exprs=exprs),
                "limit": ast.Constant(value=self.query.limit or DEFAULT_FACET_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _resource_attribute_query(self) -> ast.SelectQuery:
        key = cast(str, self.facet_resource_attribute)
        # Full cross-filtering (severity, service, body-search, other resource attrs) is possible
        # here because we read raw rows — richer than the hot rollup, which only honours service.
        filter_builder = ArchiveLogsFilterBuilder(
            self.query,
            self.team,
            self.query_date_range,
            exclude_resource_attribute=key,
        )
        exprs: list[ast.Expr] = [filter_builder.where(), self._exact_timestamp_bounds()]
        query = parse_select(
            """
            SELECT resource_attributes[{key}] AS value, count() AS count
            FROM posthog.logs_archive
            WHERE mapContains(resource_attributes, {key})
            AND resource_attributes[{key}] != ''
            AND resource_attributes[{key}] ILIKE {search}
            AND {where}
            GROUP BY value
            ORDER BY count() DESC, value ASC
            LIMIT {limit}
            """,
            placeholders={
                "key": ast.Constant(value=key),
                "search": ast.Constant(value=ilike_pattern(self.facet_search)),
                "where": ast.And(exprs=exprs),
                "limit": ast.Constant(value=self.query.limit or DEFAULT_FACET_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return HogQLGlobalSettings(
            read_overflow_mode="break",
            max_bytes_to_read=ARCHIVE_ATTRIBUTES_MAX_READ_BYTES,
            max_execution_time=ARCHIVE_ATTRIBUTES_MAX_EXECUTION_SECONDS,
        )


class ArchivedLogValuesQueryRunner(LogValuesQueryRunner):
    FILTER_BUILDER_CLASS = ArchiveLogsFilterBuilder

    def _map_column(self) -> str:
        return "resource_attributes" if self.query.attributeType == "resource" else "attributes"

    def to_query(self) -> ast.SelectQuery:
        query = parse_select(
            f"""
            SELECT
                groupArray({{limit}})((attribute_value, value_count)) as values,
                count() as total_count
            FROM (
                SELECT
                    {self._map_column()}[{{attributeKey}}] AS attribute_value,
                    count() AS value_count
                FROM posthog.logs_archive
                WHERE log_date >= toDate({{date_from_start_of_interval}})
                AND log_date <= toDate({{date_to_start_of_interval}} + {{one_interval_period}})
                AND timestamp >= {{date_from_start_of_interval}}
                AND timestamp <= {{date_to_start_of_interval}} + {{one_interval_period}}
                AND mapContains({self._map_column()}, {{attributeKey}})
                AND attribute_value ILIKE {{search}}
                AND {{where}}
                GROUP BY attribute_value
                ORDER BY lower(attribute_value) = lower({{exact}}) DESC, has(splitByNonAlpha(lower(attribute_value)), lower({{exact}})) DESC, value_count desc, attribute_value asc
                OFFSET {{offset}}
            )
            """,
            placeholders={
                "search": ast.Constant(value=ilike_pattern(self.query.search)),
                "exact": ast.Constant(value=self.query.search),
                "attributeKey": ast.Constant(value=self.query.attributeKey),
                "limit": ast.Constant(value=self.query.limit),
                "offset": ast.Constant(value=self.query.offset),
                "where": self.where(),
                **self.query_date_range.to_placeholders(),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return HogQLGlobalSettings(
            read_overflow_mode="break",
            max_bytes_to_read=ARCHIVE_ATTRIBUTES_MAX_READ_BYTES,
            max_execution_time=ARCHIVE_ATTRIBUTES_MAX_EXECUTION_SECONDS,
        )
