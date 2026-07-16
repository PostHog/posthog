"""Evaluate a VisionAction's alert condition over its observation window and persist the message.

Runs as a Temporal activity, mirroring the group-summary synthesis activity: all blocking ORM work
happens in one sync function, and the alert message is written onto `VisionActionRun` inside the
activity — it never crosses the Temporal wire. Unlike synthesis there is no LLM call: the message is
deterministic (metric, threshold, and a few example outcomes), so alerts don't bill AI credits and
don't require the AI data-processing consent gate.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Avg, FloatField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

import structlog
from temporalio import activity

from posthog.helpers.markdown_safety import strip_external_links_markdown
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.vision_action import (
    AlertDirection,
    AlertFrequency,
    AlertMetric,
    VisionActionRun,
    VisionActionRunStatus,
)
from products.replay_vision.backend.observation_formatting import describe_output
from products.replay_vision.backend.scanner_access import readable_scanner_ids
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.vision_actions.synthesis import (
    MAX_OBSERVATIONS,
    _markdown_to_slack,
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
# Rolling evaluation windows the condition may look back over, in days.
ALERT_WINDOW_DAYS = (1, 3, 7, 14, 30)
DEFAULT_ALERT_WINDOW_DAYS = 1
# Skip reasons that mean a check ran to completion and observed the alert's state.
_EVALUATED_SKIP_REASONS = {"not_breached", "still_breached"}
# How many prior runs to scan for the last meaningful evaluation before giving up (an alert with
# this many consecutive failed checks has bigger problems than firing state).
_STATE_SCAN_LIMIT = 20


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
    scanner_ids = readable_scanner_ids(creator, team, requested_scanner_ids) if creator is not None else []
    if not scanner_ids:
        return EvaluateAlertResult(status=AlertStatus.NOT_BREACHED, observation_count=0)

    alert_config: dict[str, Any] = action.alert_config or {}
    frequency = alert_config.get("frequency", AlertFrequency.ON_BREACH)
    metric = alert_config.get("metric", AlertMetric.COUNT)
    threshold = alert_config.get("threshold")
    window_days = alert_config.get("window_days", DEFAULT_ALERT_WINDOW_DAYS)
    every_match = frequency == AlertFrequency.EVERY_MATCH
    if not every_match and (
        not isinstance(threshold, int | float)
        or isinstance(threshold, bool)
        or not isinstance(window_days, int)
        or window_days not in ALERT_WINDOW_DAYS
    ):
        # Malformed config (serializer-validated, so only reachable via direct writes). Don't fire.
        logger.warning("vision_action.alert.invalid_config", vision_action_id=str(action.id))
        return EvaluateAlertResult(status=AlertStatus.NOT_BREACHED, observation_count=0)

    previous, previous_breached = _last_evaluated_run(team.id, action.id, run.pk)

    window_end = run.scheduled_at or datetime.now(UTC)
    if every_match:
        # Every-match alerts tile their windows between checks (like summaries) so each new match is
        # reported exactly once; the first check starts at the alert's creation, never dumping history.
        window_start = (previous.scheduled_at or previous.created_at) if previous else action.created_at
    else:
        # Threshold conditions look back over a rolling window ending at the run's tick, so
        # "over the last 7 days" means the same thing on every check.
        window_start = window_end - timedelta(days=window_days)

    # Windows bound on completed_at, not created_at: an observation takes minutes to process, and a
    # row created in one tick's window but succeeding during the next would never land in either if
    # windows tiled on creation time. completed_at is only set on success, so it can't move backward.
    observations_qs = apply_observation_predicate(
        ReplayObservation.objects.filter(
            team_id=team.id,
            scanner_id__in=scanner_ids,
            status=ObservationStatus.SUCCEEDED,
            completed_at__gte=window_start,
            completed_at__lt=window_end,
        ),
        selection,
    )

    matched_count = observations_qs.count()
    if every_match:
        # Any new match notifies; there's no threshold state to arm or clear.
        if matched_count == 0:
            return EvaluateAlertResult(status=AlertStatus.NOT_BREACHED, observation_count=0)
        return _persist_fired(run, action, alert_config, float(matched_count), matched_count, observations_qs, team)

    # Only on_breach flows reach here, and the config guard above validated the threshold.
    assert isinstance(threshold, int | float)

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

    # The condition is "metric at or above/below the threshold" (inclusive, per direction — see
    # AlertConfigSerializer). No measurable data (avg over an empty window) can't breach in either
    # direction; count is always measurable (0), so a below-direction count alert DOES fire on a
    # quiet window — that's its "went quiet" meaning.
    below = alert_config.get("direction") == AlertDirection.BELOW
    breached = metric_value is not None and (metric_value <= threshold if below else metric_value >= threshold)
    if not breached:
        return EvaluateAlertResult(
            status=AlertStatus.NOT_BREACHED, observation_count=matched_count, metric_value=metric_value
        )

    # Fire on the transition into breach only: a rolling window can stay breached across many checks,
    # and re-notifying every tick would be spam. The last meaningful evaluation's outcome is the state.
    if previous is not None and previous_breached:
        return EvaluateAlertResult(
            status=AlertStatus.STILL_BREACHED, observation_count=matched_count, metric_value=metric_value
        )

    return _persist_fired(run, action, alert_config, metric_value, matched_count, observations_qs, team)


def _last_evaluated_run(team_id: int, action_id: Any, exclude_pk: Any) -> tuple[VisionActionRun | None, bool]:
    """The most recent prior run whose outcome reflects the alert's state, and whether it observed a
    breach: a fired run (message persisted, even if delivery later failed) or an evaluated skip.
    Failed or interrupted checks are walked past so a transient failure can't re-arm a still-breached
    alert, and so an every-match window that a failed check never covered gets re-covered."""
    runs = (
        VisionActionRun.objects.for_team(team_id)
        .filter(vision_action_id=action_id)
        .exclude(pk=exclude_pk)
        .order_by("-created_at")[:_STATE_SCAN_LIMIT]
    )
    for prev in runs:
        if prev.synthesized_markdown:
            return prev, True
        error = prev.error if isinstance(prev.error, dict) else {}
        if prev.status == VisionActionRunStatus.SKIPPED and error.get("skip_reason") in _EVALUATED_SKIP_REASONS:
            return prev, error.get("skip_reason") == "still_breached"
    return None, False


def _persist_fired(
    run: VisionActionRun,
    action: Any,
    alert_config: dict[str, Any],
    metric_value: float,
    matched_count: int,
    observations_qs: Any,
    team: Any,
) -> EvaluateAlertResult:
    # One fetch feeds both the message and the persisted ids, so the `[obs N]` labels in the example
    # lines always agree with `observation_ids` order (which the run serializer numbers `index` by and
    # both the Slack pass and the in-app view resolve into observation links).
    rows = list(
        observations_qs.order_by("-created_at", "-id").values_list("id", "scanner_result", "created_at")[
            :MAX_OBSERVATIONS
        ]
    )
    observation_ids = [str(observation_id) for observation_id, _, _ in rows]
    markdown = strip_external_links_markdown(_alert_markdown(action, alert_config, metric_value, matched_count, rows))
    # Links are added AFTER the strip pass (like the Slack citation links) so the URLs aren't defanged
    # on instances whose SITE_URL isn't a posthog.com host (self-hosted, dev).
    run_url = _run_url(team.id, str(action.id), str(run.pk))
    markdown = _linkify_header(markdown, action, run_url)
    if matched_count > EXAMPLE_LINES:
        # More matches than the message lists as examples — point at the run page, which shows every
        # match this alert included (capped at MAX_OBSERVATIONS).
        markdown += f"\n\n[See all {matched_count:,} matches]({run_url})"
    run.synthesized_markdown = markdown
    run.output = {"slack": _markdown_to_slack(markdown, team_id=team.id, observation_ids=observation_ids)}
    run.observation_count = matched_count
    run.observation_ids = observation_ids
    run.save(update_fields=["synthesized_markdown", "output", "observation_count", "observation_ids", "updated_at"])

    return EvaluateAlertResult(status=AlertStatus.FIRED, observation_count=matched_count, metric_value=metric_value)


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def _run_url(team_id: int, action_id: str, run_id: str) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/replay-vision/actions/{action_id}/runs/{run_id}"


def _scanner_display_name(action: Any) -> str:
    # Scanner name is free text; strip markdown/mrkdwn control chars so it can't garble the bold
    # header, plus link syntax chars so it can't break out of the header link's label.
    raw_name = action.scanner.name if action.scanner_id else ""
    return re.sub(r"\s+", " ", re.sub(r"[*_`#\[\]()]", "", raw_name)).strip() or "your scanner"


def _linkify_header(markdown: str, action: Any, run_url: str) -> str:
    """Wrap the header's scanner name in a link to this alert's run page — the alert's own message
    plus every matching observation (and breadcrumbs back to the scanner). A name the strip pass
    rewrote (e.g. it contained a bare URL, now a code span) won't match the expected header — leave
    it unlinked rather than guess."""
    if not action.scanner_id:
        return markdown
    name = _scanner_display_name(action)
    prefix = f"**Alert: {name}**"
    if not markdown.startswith(prefix):
        return markdown
    return f"**Alert: [{name}]({run_url})**" + markdown[len(prefix) :]


def _alert_markdown(
    action: Any,
    alert_config: dict[str, Any],
    metric_value: float,
    matched_count: int,
    rows: list[tuple[Any, Any, datetime]],
) -> str:
    """Deterministic alert report: what fired, the measured value vs the threshold, and a few example
    observation outcomes (verdict/score/tags via `describe_output` — outcomes only, no
    recording-derived prose, so nothing here needs an LLM or invites prompt injection). Example lines
    carry `[obs N]` citation markers — N is the observation's 1-based position in `rows`
    (= `observation_ids` order) — which the Slack pass and the in-app view resolve into links to each
    observation."""
    scanner_name = _scanner_display_name(action)

    noun = "observation" if matched_count == 1 else "observations"
    if alert_config.get("frequency", AlertFrequency.ON_BREACH) == AlertFrequency.EVERY_MATCH:
        lines = [
            f"**Alert: {scanner_name}** — {matched_count} new matching {noun} since the last check.",
        ]
    else:
        metric = alert_config.get("metric", AlertMetric.COUNT)
        threshold = alert_config.get("threshold", 0)
        window_days = alert_config.get("window_days", DEFAULT_ALERT_WINDOW_DAYS)
        metric_label = "average score" if metric == AlertMetric.AVG_SCORE else "matching observations"
        window_label = "24 hours" if window_days == 1 else f"{window_days} days"
        bound = "at or below" if alert_config.get("direction") == AlertDirection.BELOW else "at or above"
        lines = [
            f"**Alert: {scanner_name}** — {metric_label} over the last {window_label} was "
            f"{_format_number(metric_value)}, {bound} the threshold of {_format_number(threshold)}.",
            "",
            f"{matched_count} {noun} matched in this window.",
        ]

    examples: list[str] = []
    for position, (_, scanner_result, created_at) in enumerate(rows[:EXAMPLE_LINES], start=1):
        output = scanner_result.get("model_output") if isinstance(scanner_result, dict) else None
        if not isinstance(output, dict):
            continue
        descriptor = describe_output(output)
        if descriptor:
            examples.append(f"- ({created_at:%Y-%m-%d}) {descriptor} [obs {position}]")
    if examples:
        lines.extend(["", "Most recent matches:", *examples])

    return "\n".join(lines)
