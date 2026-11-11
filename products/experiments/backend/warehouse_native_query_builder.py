import re
from datetime import UTC, datetime, timedelta
from functools import cached_property

from posthog.schema import (
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentWarehouseNativeExposureConfig,
    ExperimentWarehouseNativeMathType,
    ExperimentWarehouseNativeNode,
    MultipleVariantHandling,
)

from posthog.hogql.direct_sql.bigquery_adapter import ensure_read_only_raw_bigquery_statement
from posthog.hogql.direct_sql.raw_sql import nestable_direct_statement
from posthog.hogql.errors import ExposedHogQLError

from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.hogql_queries.experiment_metric_values import get_conversion_window_seconds

# The value column goes into the statement as an identifier. BigQuery escapes a quoted identifier
# with backslashes, so a plain name is the only form that needs no escaping at all.
_PLAIN_COLUMN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _source_cte(name: str, query: str, label: str) -> str:
    try:
        # The builder applies the read-only check itself, so that the check does not depend on the
        # code that runs the statement.
        statement = nestable_direct_statement(ensure_read_only_raw_bigquery_statement(query), dialect="bigquery")
    except ExposedHogQLError as error:
        raise ExposedHogQLError(f"The {label} cannot run. {error}") from error
    # The customer's query goes in without indentation, because indentation would change a string
    # that spans several lines.
    return f"{name} AS (\n{statement}\n)"


def _string_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
    return f"'{escaped}'"


def _timestamp_literal(value: datetime) -> str:
    return f"TIMESTAMP '{value.astimezone(UTC).isoformat(sep=' ')}'"


class WarehouseNativeQueryBuilder:
    """Builds the BigQuery statement that calculates one metric of a warehouse-native experiment.

    The statement runs in the customer's warehouse. It returns one row per variant, with the column
    names of the ClickHouse metric queries, so the same code can read both results. The customer's
    queries go in unchanged as CTEs. This class adds the join between the exposures and the metric
    rows, and the aggregation.

    Every CTE name starts with a prefix that no query of the customer contains, and every column
    reference names its CTE, so that no name of the customer's queries can change what a reference
    means.

    Only one CTE reads each CTE. BigQuery runs a CTE again for each reference to it, so a second
    reader would run the customer's query a second time.
    """

    def __init__(
        self,
        *,
        exposure: ExperimentWarehouseNativeExposureConfig,
        metric: ExperimentMeanMetric | ExperimentRatioMetric,
        variants: tuple[str, ...],
        date_from: datetime,
        date_to: datetime,
        multiple_variant_handling: MultipleVariantHandling,
    ):
        self.exposure = exposure
        self.metric = metric
        self.variants = variants
        self.date_from = date_from
        self.date_to = date_to
        self.multiple_variant_handling = multiple_variant_handling
        self.conversion_window_seconds = get_conversion_window_seconds(metric)

    @cached_property
    def _sources(self) -> dict[str, ExperimentWarehouseNativeNode]:
        candidates: dict[str, object]
        if isinstance(self.metric, ExperimentRatioMetric):
            candidates = {"numerator": self.metric.numerator, "denominator": self.metric.denominator}
        else:
            candidates = {"metric": self.metric.source}
        sources: dict[str, ExperimentWarehouseNativeNode] = {}
        for name, candidate in candidates.items():
            if not isinstance(candidate, ExperimentWarehouseNativeNode):
                raise ExposedHogQLError("A warehouse-native experiment can only calculate warehouse-native metrics.")
            sources[name] = candidate
        return sources

    @cached_property
    def _prefix(self) -> str:
        """The start of every CTE name.

        A CTE hides a table of the same name from every CTE after it. A customer's query that reads
        a table named like a CTE of this statement would read the CTE and not the table.
        """
        # BigQuery compares CTE names without regard to case.
        customer_text = "\n".join([self.exposure.query, *(source.query for source in self._sources.values())]).lower()
        prefix = "posthog_"
        attempt = 1
        while prefix in customer_text:
            attempt += 1
            prefix = f"posthog_{attempt}_"
        return prefix

    def _refuse_unsupported_options(self) -> None:
        """A statement that ignored one of these options would return a result that the user did not ask for."""
        if isinstance(self.metric, ExperimentRatioMetric):
            winsorized = any(
                bounds is not None
                and (bounds.lower_bound_percentile is not None or bounds.upper_bound_percentile is not None)
                for bounds in (self.metric.numerator_outlier_handling, self.metric.denominator_outlier_handling)
            )
        else:
            winsorized = (
                self.metric.lower_bound_percentile is not None or self.metric.upper_bound_percentile is not None
            )
        if winsorized:
            raise ExposedHogQLError("Warehouse-native metrics do not support outlier handling yet.")
        if self.metric.breakdownFilter is not None and self.metric.breakdownFilter.breakdowns:
            raise ExposedHogQLError("Warehouse-native metrics do not support breakdowns yet.")

    def _row_value(self, source: ExperimentWarehouseNativeNode, source_cte: str) -> str:
        if source.math != ExperimentWarehouseNativeMathType.SUM:
            return "1.0"
        if not source.math_property:
            raise ExposedHogQLError("A warehouse-native metric that sums values needs a value column.")
        if not _PLAIN_COLUMN_NAME.fullmatch(source.math_property):
            raise ExposedHogQLError(
                "The value column of a warehouse-native metric can only contain letters, numbers and underscores. "
                "Rename the column in the metric query."
            )
        return f"CAST({source_cte}.`{source.math_property}` AS FLOAT64)"

    def _exposure_ctes(self) -> list[str]:
        """One row per entity: its variant and the time of its first exposure in the experiment's date range."""
        source = f"{self._prefix}exposure_source"
        rows = f"{self._prefix}exposure_rows"
        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            variant = f"MIN_BY({rows}.variant, {rows}.exposure_time)"
        else:
            variant = (
                f"IF(COUNT(DISTINCT {rows}.variant) > 1, {_string_literal(MULTIPLE_VARIANT_KEY)}, MIN({rows}.variant))"
            )
        variants = ", ".join(_string_literal(variant_key) for variant_key in self.variants)
        return [
            _source_cte(source, self.exposure.query, "exposure query"),
            f"""{rows} AS (
    SELECT
        CAST({source}.entity_id AS STRING) AS entity_id,
        CAST({source}.variant AS STRING) AS variant,
        CAST({source}.`timestamp` AS TIMESTAMP) AS exposure_time
    FROM {source}
)""",
            f"""{self._prefix}exposures AS (
    SELECT
        {rows}.entity_id AS entity_id,
        {variant} AS variant,
        MIN({rows}.exposure_time) AS first_exposure_time
    FROM {rows}
    WHERE {rows}.exposure_time >= {_timestamp_literal(self.date_from)}
        AND {rows}.exposure_time <= {_timestamp_literal(self.date_to)}
        AND {rows}.variant IN ({variants})
        AND {rows}.entity_id IS NOT NULL
    GROUP BY {rows}.entity_id
)""",
        ]

    def _source_rows_ctes(self, name: str) -> list[str]:
        """The rows of one metric source that are in the time range of the experiment."""
        source = self._sources[name]
        source_cte = f"{self._prefix}{name}_source"
        event_time = f"CAST({source_cte}.`timestamp` AS TIMESTAMP)"
        # With a conversion window, the window of a late exposure can end after the experiment.
        last_event_time = self.date_to + timedelta(seconds=self.conversion_window_seconds)
        return [
            _source_cte(source_cte, source.query, f"{name} query"),
            f"""{self._prefix}{name}_rows AS (
    SELECT
        CAST({source_cte}.entity_id AS STRING) AS entity_id,
        {event_time} AS event_time,
        {self._row_value(source, source_cte)} AS value
    FROM {source_cte}
    WHERE {event_time} >= {_timestamp_literal(self.date_from)}
        AND {event_time} < {_timestamp_literal(last_event_time)}
)""",
        ]

    def _entity_metrics_cte(self, rows: str, value_columns: tuple[str, ...]) -> str:
        """One row per exposed entity: its variant, and for each value column the sum of the rows that count.

        A row counts from the first exposure of its entity. With a conversion window it counts until
        the window ends.
        """
        exposures = f"{self._prefix}exposures"
        window_end = ""
        if self.conversion_window_seconds > 0:
            window_end = (
                f"\n        AND {rows}.event_time < TIMESTAMP_ADD({exposures}.first_exposure_time, "
                f"INTERVAL {self.conversion_window_seconds} SECOND)"
            )
        sums = "".join(f",\n        COALESCE(SUM({rows}.{column}), 0) AS {column}" for column in value_columns)
        return f"""{self._prefix}entity_metrics AS (
    SELECT
        {exposures}.entity_id AS entity_id,
        {exposures}.variant AS variant{sums}
    FROM {exposures}
    LEFT JOIN {rows}
        ON {rows}.entity_id = {exposures}.entity_id
        AND {rows}.event_time >= {exposures}.first_exposure_time{window_end}
    GROUP BY {exposures}.entity_id, {exposures}.variant
)"""

    def _build_mean_query(self) -> str:
        assert isinstance(self.metric, ExperimentMeanMetric)
        entity_metrics = f"{self._prefix}entity_metrics"
        ctes = [
            *self._exposure_ctes(),
            *self._source_rows_ctes("metric"),
            self._entity_metrics_cte(f"{self._prefix}metric_rows", ("value",)),
        ]
        value = f"{entity_metrics}.value"
        if self.metric.threshold is not None:
            # A threshold turns the value of each entity into 1 or 0, and 1 and 0 equal their own squares.
            value = f"IF({value} >= {float(self.metric.threshold)!r}, 1, 0)"
        return f"""WITH {",\n".join(ctes)}
SELECT
    {entity_metrics}.variant AS variant,
    COUNT({entity_metrics}.entity_id) AS num_users,
    SUM({value}) AS total_sum,
    SUM({value} * {value}) AS total_sum_of_squares
FROM {entity_metrics}
GROUP BY {entity_metrics}.variant"""

    def _build_ratio_query(self) -> str:
        numerator_rows = f"{self._prefix}numerator_rows"
        denominator_rows = f"{self._prefix}denominator_rows"
        metric_rows = f"{self._prefix}metric_rows"
        entity_metrics = f"{self._prefix}entity_metrics"
        ctes = [
            *self._exposure_ctes(),
            *self._source_rows_ctes("numerator"),
            *self._source_rows_ctes("denominator"),
            # The rows of both sources go into one CTE, so that one join can read the exposures.
            f"""{metric_rows} AS (
    SELECT
        {numerator_rows}.entity_id AS entity_id,
        {numerator_rows}.event_time AS event_time,
        {numerator_rows}.value AS numerator_value,
        0.0 AS denominator_value
    FROM {numerator_rows}
    UNION ALL
    SELECT
        {denominator_rows}.entity_id AS entity_id,
        {denominator_rows}.event_time AS event_time,
        0.0 AS numerator_value,
        {denominator_rows}.value AS denominator_value
    FROM {denominator_rows}
)""",
            self._entity_metrics_cte(metric_rows, ("numerator_value", "denominator_value")),
        ]
        numerator = f"{entity_metrics}.numerator_value"
        denominator = f"{entity_metrics}.denominator_value"
        return f"""WITH {",\n".join(ctes)}
SELECT
    {entity_metrics}.variant AS variant,
    COUNT({entity_metrics}.entity_id) AS num_users,
    SUM({numerator}) AS total_sum,
    SUM({numerator} * {numerator}) AS total_sum_of_squares,
    SUM({denominator}) AS denominator_sum,
    SUM({denominator} * {denominator}) AS denominator_sum_squares,
    SUM({numerator} * {denominator}) AS numerator_denominator_sum_product
FROM {entity_metrics}
GROUP BY {entity_metrics}.variant"""

    def build(self) -> str:
        self._refuse_unsupported_options()
        if isinstance(self.metric, ExperimentRatioMetric):
            return self._build_ratio_query()
        return self._build_mean_query()
