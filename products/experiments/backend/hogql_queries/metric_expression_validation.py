"""Save-time validation for the SQL expressions users write as metric math.

A metric whose SQL expression can't be turned into a query fails identically on every run, so it
should be rejected when it is saved rather than surfacing as a query failure hours later.
"""

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
)

from posthog.hogql.errors import BaseHogQLError

from products.experiments.backend.hogql_queries.hogql_aggregation_utils import (
    UnsupportedAggregationExpressionError,
    decompose_aggregation_expr,
    unparseable_sql_expression_message,
    unsupported_sql_expression_message,
)

ValidatableMetric = ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric


def validate_metric_sql_expressions(metric: ValidatableMetric) -> None:
    """Raise a ValidationError if any of the metric's sources carries an unusable SQL expression."""
    if isinstance(metric, ExperimentMeanMetric):
        sources = [metric.source]
    elif isinstance(metric, ExperimentRatioMetric):
        sources = [metric.numerator, metric.denominator]
    else:
        return

    for source in sources:
        if getattr(source, "math", None) != ExperimentMetricMathType.HOGQL:
            continue
        expression = getattr(source, "math_hogql", None)
        if not expression:
            continue

        try:
            decompose_aggregation_expr(expression)
        except UnsupportedAggregationExpressionError as e:
            raise ValidationError(unsupported_sql_expression_message(e)) from e
        except BaseHogQLError as e:
            raise ValidationError(unparseable_sql_expression_message(e)) from e
