from typing import Protocol, cast

from rest_framework.exceptions import ValidationError

from posthog.schema import AggregationType, EntityType, RetentionQuery

from posthog.hogql.constants import LimitContext, get_breakdown_limit_for_context
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DateDatabaseField, DateTimeDatabaseField

from posthog.hogql_queries.utils.breakdowns import has_breakdown_filter
from posthog.hogql_queries.utils.data_warehouse_schema_mixin import resolve_warehouse_field
from posthog.hogql_queries.utils.query_date_range import QueryDateRangeWithIntervals
from posthog.hogql_queries.validation.validation import QueryValidationContext

# Well above the 32 intervals the insight editor allows, so only a hand-written query reaches it.
MAX_RETENTION_INTERVALS = 100

# One cohort row per interval the date range spans. Well above an all-time daily chart on a project that
# has collected events for years, which is the widest shape a saved insight reaches.
MAX_RETENTION_COHORTS = 10_000

# Both axes at their own limit would still be a million cells, so the product carries the limit that decides
# how much memory one matrix can take.
MAX_RETENTION_CELLS = 100_000

# A breakdown builds the whole matrix once per breakdown value, and `breakdown_limit` comes from the request,
# so the response needs its own limit. Set above a CSV export of a breakdown chart, which asks for the widest
# response the product itself produces.
MAX_RETENTION_RESPONSE_CELLS = 1_000_000


class SupportsRetentionMatrixSize(Protocol):
    @property
    def query_date_range(self) -> QueryDateRangeWithIntervals: ...

    @property
    def lookahead_period_count(self) -> int: ...

    @property
    def limit_context(self) -> LimitContext: ...


class DisallowCumulativeWith24HourWindows:
    code = "retention_cumulative_24_hour_windows_unsupported"

    def validate(self, context: QueryValidationContext[RetentionQuery]) -> None:
        retention_filter = context.query.retentionFilter
        if retention_filter.timeWindowMode == "24_hour_windows" and retention_filter.cumulative:
            raise ValidationError("Cumulative retention is not supported for 24 hour windows.", code=self.code)


class DisallowBreakdownsWithDataWarehouse24HourWindows:
    """The 24-hour-window builder resolves a data warehouse series without an events scan in its outer query,
    so breakdown expressions (which read events / person columns) have nothing to resolve against."""

    code = "retention_data_warehouse_24_hour_windows_breakdowns_unsupported"

    def validate(self, context: QueryValidationContext[RetentionQuery]) -> None:
        retention_filter = context.query.retentionFilter
        if retention_filter.timeWindowMode != "24_hour_windows":
            return
        if not has_breakdown_filter(context.query.breakdownFilter):
            return
        has_data_warehouse_series = any(
            entity is not None and entity.type == EntityType.DATA_WAREHOUSE
            for entity in (retention_filter.targetEntity, retention_filter.returningEntity)
        )
        if has_data_warehouse_series:
            raise ValidationError(
                "Breakdowns are not supported for 24 hour windows with a data warehouse series.",
                code=self.code,
            )


class DisallowGroupAggregationWithDataWarehouse24HourWindows:
    """The 24-hour-window data warehouse scans identify actors by each entity's aggregation_target_field and join
    the arms on it directly, so a group-typed events side contributes its $group_N key: the join keys mismatch in
    type and empty group keys are not filtered out. The fixed-interval builder resolves group actors per arm and
    stays allowed."""

    code = "retention_data_warehouse_24_hour_windows_group_aggregation_unsupported"

    def validate(self, context: QueryValidationContext[RetentionQuery]) -> None:
        if context.query.aggregation_group_type_index is None:
            return
        retention_filter = context.query.retentionFilter
        if retention_filter.timeWindowMode != "24_hour_windows":
            return
        has_data_warehouse_series = any(
            entity is not None and entity.type == EntityType.DATA_WAREHOUSE
            for entity in (retention_filter.targetEntity, retention_filter.returningEntity)
        )
        if has_data_warehouse_series:
            raise ValidationError(
                "Group aggregation is not supported for 24 hour windows with a data warehouse series.",
                code=self.code,
            )


class DisallowUnsupportedDataWarehouseTimestampField:
    """Every interval bucket runs the configured timestamp column through toStartOfInterval, so a column that
    cannot be a datetime fails deep inside ClickHouse, quoting generated SQL the user never wrote. Resolving
    the column type up front turns that into a 400 naming the column they picked.

    An integer is rejected rather than converted because it could hold seconds, milliseconds or microseconds
    since the epoch, and guessing wrong shifts every bucket instead of failing."""

    code = "retention_data_warehouse_timestamp_field_unsupported"

    def validate(self, context: QueryValidationContext[RetentionQuery]) -> None:
        retention_filter = context.query.retentionFilter
        entities = [
            entity
            for entity in (retention_filter.targetEntity, retention_filter.returningEntity)
            if entity is not None and entity.type == EntityType.DATA_WAREHOUSE
        ]
        if not entities:
            return

        database = Database.create_for(team=context.team, user=context.user)
        for entity in entities:
            if not entity.table_name or not entity.timestamp_field:
                # A half-configured entity raises its own error while building the query.
                continue
            field = resolve_warehouse_field(database, entity.table_name, entity.timestamp_field)
            if not isinstance(field, DateTimeDatabaseField | DateDatabaseField):
                raise ValidationError(
                    f"{entity.table_name}.{entity.timestamp_field} can't be used as the retention timestamp, "
                    "because it isn't a date or datetime column. Pick a different column, "
                    "or convert this one in a saved query first.",
                    code=self.code,
                )


class RequireRetentionDataWarehouseEntitiesForCustomAggregationTarget:
    """The "Custom entities" aggregation target is only available when both retention entities read from the
    data warehouse. Other entities are person/group based."""

    code = "retention_custom_aggregation_target_requires_data_warehouse_entities"

    def validate(self, context: QueryValidationContext[RetentionQuery]) -> None:
        retention_filter = context.query.retentionFilter
        if not retention_filter.customAggregationTarget:
            return
        both_entities_data_warehouse = all(
            entity is not None and entity.type == EntityType.DATA_WAREHOUSE
            for entity in (retention_filter.targetEntity, retention_filter.returningEntity)
        )
        if both_entities_data_warehouse:
            return
        raise ValidationError(
            "Custom entity aggregation target requires both retention entities to be data warehouse entities.",
            code=self.code,
        )


class DisallowPropertyAggregationWith24HourWindows:
    """The 24-hour-window builder never emits the retention_value column that sum/avg aggregation reads in the
    outer query."""

    code = "retention_24_hour_windows_property_aggregation_unsupported"

    def validate(self, context: QueryValidationContext[RetentionQuery]) -> None:
        retention_filter = context.query.retentionFilter
        if retention_filter.timeWindowMode != "24_hour_windows":
            return
        has_property_aggregation = (
            retention_filter.aggregationType in (AggregationType.SUM, AggregationType.AVG)
            and retention_filter.aggregationProperty
        )
        if has_property_aggregation:
            raise ValidationError(
                "Sum and average aggregation are not supported for 24 hour windows.",
                code=self.code,
            )


class DisallowExcessiveIntervals:
    """The result matrix has one cell for each pair of a start interval and a return interval, and the query
    builds every cell in Python, so its cost is the product of the two axes. The request sets each axis on its
    own: the columns through `totalIntervals` or the custom brackets, the rows through the number of intervals
    the date range spans, which is why a limit on one axis alone still leaves a query that allocates for
    millions of cells. The row count also sizes the `date_range` array that ClickHouse builds for every
    actor."""

    code = "retention_too_many_intervals"

    def validate(self, context: QueryValidationContext[RetentionQuery]) -> None:
        retention_filter = context.query.retentionFilter
        requested: float = retention_filter.totalIntervals or 0
        brackets = retention_filter.retentionCustomBrackets
        if brackets:
            requested = max(requested, len(brackets), sum(brackets))
        if requested > MAX_RETENTION_INTERVALS:
            raise ValidationError(
                f"Retention supports up to {MAX_RETENTION_INTERVALS} intervals. "
                "Ask for fewer intervals, or use a longer period.",
                code=self.code,
            )

        runner = cast(SupportsRetentionMatrixSize, context.runner)
        cohorts = runner.query_date_range.intervals_between
        if cohorts > MAX_RETENTION_COHORTS:
            raise ValidationError(
                f"Retention supports up to {MAX_RETENTION_COHORTS:,} cohorts. "
                "Shorten the date range, or use a longer period.",
                code=self.code,
            )

        cells = cohorts * runner.lookahead_period_count
        if cells > MAX_RETENTION_CELLS:
            raise ValidationError(
                f"Retention supports up to {MAX_RETENTION_CELLS:,} cells, and this query asks for {cells:,}. "
                "Shorten the date range, or ask for fewer intervals.",
                code=self.code,
            )

        response_cells = cells * self._matrix_count(context, runner)
        if response_cells > MAX_RETENTION_RESPONSE_CELLS:
            raise ValidationError(
                f"Retention supports up to {MAX_RETENTION_RESPONSE_CELLS:,} cells across a breakdown, and this "
                f"query asks for {response_cells:,}. Break down by fewer values, shorten the date range, "
                "or ask for fewer intervals.",
                code=self.code,
            )

    def _matrix_count(
        self, context: QueryValidationContext[RetentionQuery], runner: SupportsRetentionMatrixSize
    ) -> int:
        breakdown_filter = context.query.breakdownFilter
        if not has_breakdown_filter(breakdown_filter):
            return 1
        assert breakdown_filter is not None
        requested = breakdown_filter.breakdown_limit
        if requested is None:
            requested = get_breakdown_limit_for_context(runner.limit_context)
        # The values past the limit fold into one more matrix, labelled "Other".
        return max(requested, 0) + 1
