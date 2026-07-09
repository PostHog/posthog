"""Evaluate a VisionAction's alert condition over its observation window and persist the message.

Runs as a Temporal activity, mirroring the group-summary synthesis activity: all blocking ORM work
happens in one sync function, and the alert message is written onto `VisionActionRun` inside the
activity — it never crosses the Temporal wire. Unlike synthesis there is no LLM call: the message is
deterministic (metric, threshold, and a few example outcomes), so alerts don't bill AI credits and
don't require the AI data-processing consent gate.
"""

import re
import operator
from typing import Any

from django.db.models import Avg, FloatField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

import structlog
from temporalio import activity

from posthog.helpers.markdown_safety import strip_external_links_markdown
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.vision_action import AlertMetric, AlertOperator, VisionActionRun
from products.replay_vision.backend.observation_formatting import describe_output
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.vision_actions.synthesis import (
    MAX_OBSERVATIONS,
    _markdown_to_slack,
    _readable_scanner_ids,
    _window_end,
    _window_start,
    apply_observation_predicate,
)
from products.replay_vision.backend.temporal.vision_actions.types import (
    AlertStatus,
    EvaluateAlertInputs,
    EvaluateAlertResult,
)

logger = structlog.get_logger(__name__)

# How many matching observations the alert message lists as examples.
EXAMPLE_LINES = 5

_OPERATORS = {
    AlertOperator.GT: operator.gt,
    AlertOperator.GTE: operator.ge,
    AlertOperator.LT: operator.lt,
    AlertOperator.LTE: operator.le,
    AlertOperator.EQ: operator.eq,
}

_OPERATOR_LABELS = {
    AlertOperator.GT: "above",
    AlertOperator.GTE: "at or above",
    AlertOperator.LT: "below",
    AlertOperator.LTE: "at or below",
    AlertOperator.EQ: "equal to",
}


@activity.defn
@track_activity()
async def evaluate_alert_activity(inputs: EvaluateAlertInputs) -> EvaluateAlertResult:
    return await database_sync_to_async(_evaluate, thread_sensitive=False)(inputs)


def _evaluate(inputs: EvaluateAlertInputs) -> EvaluateAlertResult:
    run = (
        VisionActionRun.objects.for_team(inputs.team_id)
        .select_related("vision_action", "vision_action__scanner", "team", "vision_action__created_by")
        .get(pk=inputs.run_id)
    )
    action = run.vision_action
    team = run.team

    # Idempotency: a retry after the message was already persisted must re-report FIRED, not re-evaluate
    # against a window that may have shifted.
    if run.synthesized_markdown:
        return EvaluateAlertResult(status=AlertStatus.FIRED, observation_count=run.observation_count)

    selection: dict[str, Any] = action.selection or {}
    requested_scanner_ids = selection.get("scanner_ids") or ([str(action.scanner_id)] if action.scanner_id else [])
    # Same creator-RBAC gate as synthesis: the alert surfaces observation outcomes, so it must not read
    # a scanner its creator can't access.
    creator = action.created_by
    scanner_ids = _readable_scanner_ids(creator, team, requested_scanner_ids) if creator is not None else []
    if not scanner_ids:
        return EvaluateAlertResult(status=AlertStatus.NOT_BREACHED, observation_count=0)

    window_start = _window_start(team, action, run)
    observations_qs = apply_observation_predicate(
        ReplayObservation.objects.filter(
            team_id=team.id,
            scanner_id__in=scanner_ids,
            status=ObservationStatus.SUCCEEDED,
            created_at__gte=window_start,
            created_at__lt=_window_end(run),
        ),
        selection,
    )

    alert_config: dict[str, Any] = action.alert_config or {}
    metric = alert_config.get("metric", AlertMetric.COUNT)
    op = alert_config.get("operator", AlertOperator.GTE)
    threshold = alert_config.get("threshold")
    compare = _OPERATORS.get(op)
    if compare is None or not isinstance(threshold, int | float) or isinstance(threshold, bool):
        # Malformed config (serializer-validated, so only reachable via direct writes). Don't fire.
        logger.warning("vision_action.alert.invalid_config", vision_action_id=str(action.id))
        return EvaluateAlertResult(status=AlertStatus.NOT_BREACHED, observation_count=0)

    matched_count = observations_qs.count()
    if metric == AlertMetric.AVG_SCORE:
        # Cast the JSONB score to float and average it; observations without a score (non-scorers)
        # are NULL and fall out of the average.
        metric_value = observations_qs.annotate(
            _score=Cast(
                KeyTextTransform("score", KeyTextTransform("model_output", "scanner_result")),
                output_field=FloatField(),
            )
        ).aggregate(avg=Avg("_score"))["avg"]
    else:
        metric_value = float(matched_count)

    # No measurable data (e.g. avg over an empty window) can't breach anything — including a
    # "count lt N" condition, which zero observations WOULD satisfy; count is always measurable (0).
    if metric_value is None or not compare(metric_value, threshold):
        return EvaluateAlertResult(
            status=AlertStatus.NOT_BREACHED, observation_count=matched_count, metric_value=metric_value
        )

    markdown = strip_external_links_markdown(
        _alert_markdown(action, metric, op, threshold, metric_value, matched_count, observations_qs)
    )
    run.synthesized_markdown = markdown
    run.output = {"slack": _markdown_to_slack(markdown)}
    run.observation_count = matched_count
    run.observation_ids = [
        str(observation_id)
        for observation_id in observations_qs.order_by("-created_at", "-id").values_list("id", flat=True)[
            :MAX_OBSERVATIONS
        ]
    ]
    run.save(update_fields=["synthesized_markdown", "output", "observation_count", "observation_ids", "updated_at"])

    return EvaluateAlertResult(status=AlertStatus.FIRED, observation_count=matched_count, metric_value=metric_value)


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def _alert_markdown(
    action: Any,
    metric: str,
    op: str,
    threshold: float,
    metric_value: float,
    matched_count: int,
    observations_qs: Any,
) -> str:
    """Deterministic alert report: what fired, the measured value vs the threshold, and a few example
    observation outcomes (verdict/score/tags via `describe_output` — outcomes only, no
    recording-derived prose, so nothing here needs an LLM or invites prompt injection)."""
    # Scanner name is free text; strip markdown/mrkdwn control chars so it can't garble the bold header.
    raw_name = action.scanner.name if action.scanner_id else ""
    scanner_name = re.sub(r"\s+", " ", re.sub(r"[*_`#]", "", raw_name)).strip() or "your scanner"

    metric_label = "average score" if metric == AlertMetric.AVG_SCORE else "matching observations"
    op_label = _OPERATOR_LABELS.get(AlertOperator(op), op)
    noun = "observation" if matched_count == 1 else "observations"

    lines = [
        f"**Alert: {scanner_name}** — {metric_label} was {_format_number(metric_value)}, "
        f"{op_label} the threshold of {_format_number(threshold)}.",
        "",
        f"{matched_count} {noun} matched in this window.",
    ]

    examples: list[str] = []
    for scanner_result, created_at in observations_qs.order_by("-created_at", "-id").values_list(
        "scanner_result", "created_at"
    )[:EXAMPLE_LINES]:
        output = scanner_result.get("model_output") if isinstance(scanner_result, dict) else None
        if not isinstance(output, dict):
            continue
        descriptor = describe_output(output)
        if descriptor:
            examples.append(f"- ({created_at:%Y-%m-%d}) {descriptor}")
    if examples:
        lines.extend(["", "Most recent matches:", *examples])

    return "\n".join(lines)
