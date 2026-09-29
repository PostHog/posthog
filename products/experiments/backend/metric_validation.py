"""Intrinsic validation for an experiment metric definition.

Inline metrics (on the experiment) and saved/shared metrics (ExperimentSavedMetric.query) are the same
metric types, so both write paths parse and validate through `parse_and_validate_metric`. Checks that need
context (team ownership, permissions, whether a referenced event or action exists) stay with the callers.
"""

import pydantic
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetric as ExperimentMetricUnion,
    ExperimentRetentionMetric,
)

from products.experiments.backend.hogql_queries.base_query_utils import is_threshold_supported_math
from products.experiments.backend.hogql_queries.funnel_validation import FunnelDWValidator
from products.experiments.backend.hogql_queries.retention_validation import retention_metric_error
from products.experiments.backend.models.experiment import LEGACY_METRIC_KINDS
from products.experiments.backend.temporal.metric_resolution import METRIC_BUILDERS, ExperimentMetric

# Cap reported pydantic errors so a funnel with many steps (each producing union-variant
# errors) cannot blow up the response size. The first N errors are the most actionable.
MAX_REPORTED_METRIC_ERRORS = 15

EVENTS_NODE_ID_HINT = (
    "EventsNode does not accept an 'id' field. "
    "To reference an event, use {'kind': 'EventsNode', 'event': '<event_name>'} (omit 'id'). "
    "To reference an action, switch to {'kind': 'ActionsNode', 'id': <integer_action_id>} (omit 'event')."
)


def is_events_node_actions_node_confusion(err: dict) -> bool:
    """An `id` field was passed on an EventsNode (probably meant ActionsNode)."""
    loc = tuple(err.get("loc") or ())
    if len(loc) < 2 or err.get("type") != "extra_forbidden":
        return False
    return loc[-1] == "id" and "EventsNode" in loc


def _metric_validation_hint(safe_errors: list[dict]) -> str:
    """Return a targeted hint for an observed pydantic error pattern, or '' if none applies.

    The structural shape of valid metrics is conveyed by `safe_errors` itself (loc, type,
    msg) — adding prose duplicates the pydantic models and rots silently. Only hints
    whose facts are independent of metric shape belong here."""
    for err in safe_errors:
        if is_events_node_actions_node_confusion(err):
            return EVENTS_NODE_ID_HINT
    return ""


def _pydantic_error_message(e: pydantic.ValidationError) -> str:
    # Surface only the field locations and error types from pydantic — not the
    # echoed `input`, `ctx`, and `url` fields, which would reflect arbitrary
    # user data back into the response (potentially unbounded in size).
    safe_errors = [{"loc": err.get("loc"), "type": err.get("type"), "msg": err.get("msg")} for err in e.errors()]
    hint = _metric_validation_hint(safe_errors)
    if len(safe_errors) > MAX_REPORTED_METRIC_ERRORS:
        truncated = safe_errors[:MAX_REPORTED_METRIC_ERRORS]
        truncated.append({"truncated": f"...{len(safe_errors) - MAX_REPORTED_METRIC_ERRORS} more"})
        safe_errors = truncated
    suffix = f" {hint}" if hint else ""
    return f"{safe_errors}.{suffix}"


def _semantic_error(metric: ExperimentMetric) -> str | None:
    """Rules the pydantic schema cannot express. FunnelDWValidator raises its own structured error."""
    if isinstance(metric, ExperimentFunnelMetric):
        # The experiment exposure event is prepended as step_0 at query time,
        # so series must contain at least one user-supplied step for the funnel
        # to yield a meaningful conversion metric.
        if not metric.series:
            return (
                "funnel metrics require at least one step. "
                "The experiment exposure event is added as the initial step automatically."
            )
        FunnelDWValidator.validate_funnel_metric(metric)
    elif isinstance(metric, ExperimentMeanMetric) and metric.threshold is not None:
        # A threshold turns the per-user value into a binary "did the user reach N"
        # outcome, which only makes sense for sum/count math types.
        if not is_threshold_supported_math(getattr(metric.source, "math", None)):
            return "a threshold is only supported for sum or count (total) math types."
        # A non-positive threshold is satisfied by every user (missing users
        # accumulate to 0), producing a meaningless 100% proportion.
        if metric.threshold <= 0:
            return "threshold must be a positive number."
        # Winsorization caps continuous outliers, which is meaningless once the
        # value collapses to a binary threshold outcome.
        if metric.lower_bound_percentile is not None or metric.upper_bound_percentile is not None:
            return "a threshold cannot be combined with outlier handling (winsorization)."
    elif isinstance(metric, ExperimentRetentionMetric):
        return retention_metric_error(metric)
    return None


def parse_and_validate_metric(metric: object, *, error_prefix: str) -> ExperimentMetric:
    """Parse a metric payload into its schema type and apply the intrinsic metric rules.

    `error_prefix` locates the metric in the request, for example "Invalid metric at index 2: ".
    """
    if not isinstance(metric, dict):
        raise ValidationError(f"{error_prefix}must be a dict")

    kind = metric.get("kind")
    if kind in LEGACY_METRIC_KINDS:
        raise ValidationError(
            f"{error_prefix}legacy metric kind '{kind}' is no longer supported. Use 'ExperimentMetric' instead."
        )
    if kind != "ExperimentMetric":
        raise ValidationError(f"{error_prefix}metric kind must be 'ExperimentMetric'")

    metric_type = metric.get("metric_type")
    if metric_type is None:
        raise ValidationError(f"{error_prefix}ExperimentMetric requires a metric_type")
    if not isinstance(metric_type, str) or metric_type not in METRIC_BUILDERS:
        raise ValidationError(
            f"{error_prefix}ExperimentMetric metric_type must be 'mean', 'funnel', 'ratio', or 'retention'"
        )

    try:
        # ExperimentMetric is a RootModel over a union discriminated by metric_type, so pydantic
        # reports errors for the chosen variant only, and .root is the concrete metric type.
        parsed = ExperimentMetricUnion.model_validate(metric).root
    except pydantic.ValidationError as e:
        raise ValidationError(f"{error_prefix}{_pydantic_error_message(e)}")

    error = _semantic_error(parsed)
    if error:
        raise ValidationError(f"{error_prefix}{error}")
    return parsed
