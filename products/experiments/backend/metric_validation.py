"""Validation for an experiment metric definition, shared by the metric write paths.

Inline metrics (on the experiment) and saved/shared metrics (ExperimentSavedMetric.query) are the same
metric types, so both write paths parse and validate through `parse_and_validate_metric`, check
referenced actions through `validate_metric_action_ids`, and check conversion windows through
`first_unitless_conversion_window`. Checks that need a user or that the caller can
waive (team ownership, permissions, whether a referenced event exists) stay with the callers.
"""

from collections.abc import Mapping, MutableSequence, Sequence
from typing import Any

import pydantic
import structlog
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    Breakdown,
    BreakdownAttributionType,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetric as ExperimentMetricUnion,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
)

from products.actions.backend.models.action import Action
from products.experiments.backend.hogql_queries.base_query_utils import is_threshold_supported_math
from products.experiments.backend.hogql_queries.funnel_validation import FunnelDWValidator
from products.experiments.backend.hogql_queries.retention_validation import retention_metric_error
from products.experiments.backend.metric_resolution import METRIC_BUILDERS, ExperimentMetric
from products.experiments.backend.models.experiment import LEGACY_METRIC_KINDS

logger = structlog.get_logger(__name__)

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
    if isinstance(kind, str) and kind in LEGACY_METRIC_KINDS:
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


class _SavedMetricLinkOverrides(pydantic.BaseModel):
    """The link metadata keys that `resolve_saved_metric_definition` applies to the saved query, typed
    as the metric schema types them. Other keys, such as `type`, are not overrides."""

    model_config = pydantic.ConfigDict(extra="ignore")

    breakdowns: list[Breakdown] | None = pydantic.Field(default=None, max_length=3)
    breakdown_limit: int | None = None
    breakdownAttributionType: BreakdownAttributionType | None = None
    breakdownAttributionValue: int | None = None


def validate_saved_metric_link_overrides(metadata: dict, *, error_prefix: str) -> None:
    """Validate the per-experiment overrides on a saved metric link.

    Every calculation applies the overrides to the saved query. An override that the metric schema
    rejects makes each calculation of that metric fail until someone edits the link.
    """
    try:
        _SavedMetricLinkOverrides.model_validate(metadata)
    except pydantic.ValidationError as e:
        raise ValidationError(f"{error_prefix}{_pydantic_error_message(e)}")


def extract_entity_nodes(metrics: list[dict] | None) -> tuple[set[str], set[int]]:
    """Extract event names and action IDs from all EventsNode/ActionsNode refs in metrics."""
    event_names: set[str] = set()
    action_ids: set[int] = set()
    if not metrics:
        return event_names, action_ids

    for metric in metrics:
        nodes: list[dict] = []
        metric_type = metric.get("metric_type")
        if metric_type == "mean":
            if source := metric.get("source"):
                nodes.append(source)
        elif metric_type == "funnel":
            nodes.extend(metric.get("series") or [])
        elif metric_type == "ratio":
            if num := metric.get("numerator"):
                nodes.append(num)
            if den := metric.get("denominator"):
                nodes.append(den)
        elif metric_type == "retention":
            if se := metric.get("start_event"):
                nodes.append(se)
            if ce := metric.get("completion_event"):
                nodes.append(ce)

        for node in nodes:
            kind = node.get("kind")
            if kind == "EventsNode":
                event = node.get("event")
                # Treat None and empty/whitespace-only strings as "no event"
                # (semantically equivalent to "All events"). The pydantic
                # schema permits "" but it can't reference a real event.
                if isinstance(event, str) and event.strip():
                    event_names.add(event)
                elif event is not None and not isinstance(event, str):
                    # Pydantic should have rejected non-str/None upstream;
                    # log so we can catch any path that bypassed validation
                    # rather than silently dropping the value.
                    logger.warning(
                        "experiment_metric_unexpected_event_type",
                        event_type=type(event).__name__,
                        event_value=repr(event)[:100],
                    )
            elif kind == "ActionsNode":
                if (action_id := node.get("id")) is not None:
                    action_ids.add(int(action_id))

    return event_names, action_ids


def validate_metric_action_ids(
    metrics: list[dict] | None, team_id: int, *, known_action_ids: set[int] | None = None
) -> None:
    """Validate that all ActionsNode IDs reference existing, non-deleted actions for the team.

    Actions are explicitly created entities with stable IDs, so a reference to a
    nonexistent action is almost certainly a mistake, so we raise a hard validation error.

    ``known_action_ids`` exempts ids already persisted on the experiment or the saved
    metric, so an update is checked for what it introduces rather than for everything it
    resends. Without it, deleting a referenced action makes every later metric
    edit fail on the resent arrays. See ``update_experiment``.
    """
    _, action_ids = extract_entity_nodes(metrics)
    if known_action_ids:
        action_ids -= known_action_ids
    if not action_ids:
        return

    existing_ids = set(
        Action.objects.filter(
            id__in=action_ids,
            team_id=team_id,
            deleted=False,
        ).values_list("id", flat=True)
    )
    missing = action_ids - existing_ids
    if missing:
        missing_str = ", ".join(str(aid) for aid in sorted(missing))
        raise ValidationError(
            f"Action(s) with ID {missing_str} not found or deleted. "
            "Each ActionsNode must reference an existing action belonging to this project."
        )


UNITLESS_CONVERSION_WINDOW_ERROR = (
    "conversion_window is set but conversion_window_unit is missing. A window without a unit is "
    "ignored, so the metric counts events until the experiment ends. Set conversion_window_unit to "
    f"one of {', '.join(repr(unit.value) for unit in FunnelConversionWindowTimeUnit)}, "
    "or remove conversion_window."
)

UNITLESS_CONVERSION_WINDOW_UUID_HINT = (
    "This metric has no uuid, but a stored metric on this experiment has the same window. To leave the "
    "stored metric unchanged, resend it with its uuid."
)


def _has_unitless_conversion_window(metric: Any) -> bool:
    if not isinstance(metric, Mapping):
        return False
    return metric.get("conversion_window") is not None and not metric.get("conversion_window_unit")


def _is_same_stored_metric(metric: Mapping[str, Any], stored: Any) -> bool:
    """True when `stored` is the same metric, still carrying the same unit-less window.

    Identity is the uuid as sent. Metrics written before uuids were assigned have none, and two
    missing uuids compare equal, so those match on the window alone.
    """
    if not _has_unitless_conversion_window(stored):
        return False
    return stored.get("uuid") == metric.get("uuid") and stored.get("conversion_window") == metric.get(
        "conversion_window"
    )


def first_unitless_conversion_window(
    metrics: Sequence[Any] | None,
    unmatched_stored_metrics: MutableSequence[Any],
) -> int | None:
    """Index of the first metric that sets a conversion window without a unit, or None.

    A metric already present in `unmatched_stored_metrics` with the same unit-less window is
    skipped. Metric lists are whole-array fields, so an update that changes one metric resends
    them all, and experiments written before this rule hold unit-less windows that must stay
    editable.

    Each match is consumed, so one stored metric excuses one incoming metric and a second copy of
    it is read as the new metric it becomes. Pass one list across both metric sections to count a
    match in either.
    """
    for index, metric in enumerate(metrics or []):
        if not _has_unitless_conversion_window(metric):
            continue
        matched = next(
            (
                position
                for position, stored in enumerate(unmatched_stored_metrics)
                if _is_same_stored_metric(metric, stored)
            ),
            None,
        )
        if matched is None:
            return index
        del unmatched_stored_metrics[matched]
    return None


def is_stored_metric_without_uuid(metric: Any, unmatched_stored_metrics: Sequence[Any]) -> bool:
    """True when `metric` has no uuid but carries the unit-less window of a stored metric that has one.

    The match keys on the uuid as sent, so a stored metric resent without its uuid reads as a new
    metric and is rejected. A caller that dropped the uuid needs to hear that, not only the unit rule.
    """
    if not isinstance(metric, Mapping) or metric.get("uuid"):
        return False
    return any(
        _has_unitless_conversion_window(stored)
        and stored.get("uuid")
        and stored.get("conversion_window") == metric.get("conversion_window")
        for stored in unmatched_stored_metrics
    )
