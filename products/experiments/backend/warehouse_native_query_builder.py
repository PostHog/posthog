import re
from datetime import UTC, datetime, timedelta

from posthog.schema import (
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentWarehouseNativeExposureConfig,
    ExperimentWarehouseNativeMathType,
    ExperimentWarehouseNativeNode,
    MultipleVariantHandling,
)

from posthog.hogql.direct_sql.raw_sql import nestable_direct_statement
from posthog.hogql.errors import ExposedHogQLError

from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.hogql_queries.experiment_metric_values import get_conversion_window_seconds

# The value column goes into the statement as an identifier. BigQuery escapes a quoted identifier
# with backslashes, so a plain name is the only form that needs no escaping at all.
_PLAIN_COLUMN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _source_cte(name: str, query: str, label: str) -> str:
    try:
        statement = nestable_direct_statement(query, dialect="bigquery")
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

    Every CTE name starts with `posthog_`, and every column reference names its CTE, so that no
    name of the customer's queries can change what a reference means.
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
        if self.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            variant = "MIN_BY(posthog_exposure_rows.variant, posthog_exposure_rows.exposure_time)"
        else:
            variant = (
                f"IF(COUNT(DISTINCT posthog_exposure_rows.variant) > 1, {_string_literal(MULTIPLE_VARIANT_KEY)}, "
                "MIN(posthog_exposure_rows.variant))"
            )
        variants = ", ".join(_string_literal(variant_key) for variant_key in self.variants)
        return [
            _source_cte("posthog_exposure_source", self.exposure.query, "exposure query"),
            """posthog_exposure_rows AS (
    SELECT
        CAST(posthog_exposure_source.entity_id AS STRING) AS entity_id,
        CAST(posthog_exposure_source.variant AS STRING) AS variant,
        CAST(posthog_exposure_source.`timestamp` AS TIMESTAMP) AS exposure_time
    FROM posthog_exposure_source
)""",
            f"""posthog_exposures AS (
    SELECT
        posthog_exposure_rows.entity_id AS entity_id,
        {variant} AS variant,
        MIN(posthog_exposure_rows.exposure_time) AS first_exposure_time
    FROM posthog_exposure_rows
    WHERE posthog_exposure_rows.exposure_time >= {_timestamp_literal(self.date_from)}
        AND posthog_exposure_rows.exposure_time <= {_timestamp_literal(self.date_to)}
        AND posthog_exposure_rows.variant IN ({variants})
        AND posthog_exposure_rows.entity_id IS NOT NULL
    GROUP BY posthog_exposure_rows.entity_id
)""",
        ]

    def _entity_value_ctes(self, name: str, source: object, label: str) -> list[str]:
        """One row per exposed entity that has rows of this source: the sum of its values that count."""
        if not isinstance(source, ExperimentWarehouseNativeNode):
            raise ExposedHogQLError("A warehouse-native experiment can only calculate warehouse-native metrics.")
        rows = f"posthog_{name}_rows"
        source_cte = f"posthog_{name}_source"

        # A row counts from the first exposure of its entity. With a conversion window it counts
        # until the window ends, and the window of a late exposure can end after the experiment.
        last_event_time = self.date_to + timedelta(seconds=self.conversion_window_seconds)
        window_end = ""
        if self.conversion_window_seconds > 0:
            window_end = (
                f"\n        AND {rows}.event_time < TIMESTAMP_ADD(posthog_exposures.first_exposure_time, "
                f"INTERVAL {self.conversion_window_seconds} SECOND)"
            )
        return [
            _source_cte(source_cte, source.query, label),
            f"""{rows} AS (
    SELECT
        CAST({source_cte}.entity_id AS STRING) AS entity_id,
        CAST({source_cte}.`timestamp` AS TIMESTAMP) AS event_time,
        {self._row_value(source, source_cte)} AS value
    FROM {source_cte}
)""",
            f"""posthog_{name}_values AS (
    SELECT
        posthog_exposures.entity_id AS entity_id,
        SUM({rows}.value) AS value
    FROM posthog_exposures
    INNER JOIN {rows}
        ON {rows}.entity_id = posthog_exposures.entity_id
        AND {rows}.event_time >= posthog_exposures.first_exposure_time{window_end}
    WHERE {rows}.event_time >= {_timestamp_literal(self.date_from)}
        AND {rows}.event_time < {_timestamp_literal(last_event_time)}
    GROUP BY posthog_exposures.entity_id
)""",
        ]

    def _build_mean_query(self) -> str:
        assert isinstance(self.metric, ExperimentMeanMetric)
        ctes = [
            *self._exposure_ctes(),
            *self._entity_value_ctes("metric", self.metric.source, "metric query"),
            """posthog_entity_metrics AS (
    SELECT
        posthog_exposures.entity_id AS entity_id,
        posthog_exposures.variant AS variant,
        COALESCE(posthog_metric_values.value, 0) AS value
    FROM posthog_exposures
    LEFT JOIN posthog_metric_values
        ON posthog_metric_values.entity_id = posthog_exposures.entity_id
)""",
        ]
        value = "posthog_entity_metrics.value"
        if self.metric.threshold is not None:
            # A threshold turns the value of each entity into 1 or 0, and 1 and 0 equal their own squares.
            value = f"IF({value} >= {float(self.metric.threshold)!r}, 1, 0)"
        return f"""WITH {",\n".join(ctes)}
SELECT
    posthog_entity_metrics.variant AS variant,
    COUNT(posthog_entity_metrics.entity_id) AS num_users,
    SUM({value}) AS total_sum,
    SUM({value} * {value}) AS total_sum_of_squares
FROM posthog_entity_metrics
GROUP BY posthog_entity_metrics.variant"""

    def _build_ratio_query(self) -> str:
        assert isinstance(self.metric, ExperimentRatioMetric)
        ctes = [
            *self._exposure_ctes(),
            *self._entity_value_ctes("numerator", self.metric.numerator, "numerator query"),
            *self._entity_value_ctes("denominator", self.metric.denominator, "denominator query"),
            """posthog_entity_metrics AS (
    SELECT
        posthog_exposures.entity_id AS entity_id,
        posthog_exposures.variant AS variant,
        COALESCE(posthog_numerator_values.value, 0) AS numerator_value,
        COALESCE(posthog_denominator_values.value, 0) AS denominator_value
    FROM posthog_exposures
    LEFT JOIN posthog_numerator_values
        ON posthog_numerator_values.entity_id = posthog_exposures.entity_id
    LEFT JOIN posthog_denominator_values
        ON posthog_denominator_values.entity_id = posthog_exposures.entity_id
)""",
        ]
        numerator = "posthog_entity_metrics.numerator_value"
        denominator = "posthog_entity_metrics.denominator_value"
        return f"""WITH {",\n".join(ctes)}
SELECT
    posthog_entity_metrics.variant AS variant,
    COUNT(posthog_entity_metrics.entity_id) AS num_users,
    SUM({numerator}) AS total_sum,
    SUM({numerator} * {numerator}) AS total_sum_of_squares,
    SUM({denominator}) AS denominator_sum,
    SUM({denominator} * {denominator}) AS denominator_sum_squares,
    SUM({numerator} * {denominator}) AS numerator_denominator_sum_product
FROM posthog_entity_metrics
GROUP BY posthog_entity_metrics.variant"""

    def build(self) -> str:
        self._refuse_unsupported_options()
        if isinstance(self.metric, ExperimentRatioMetric):
            return self._build_ratio_query()
        return self._build_mean_query()
