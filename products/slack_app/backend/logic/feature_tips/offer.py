"""Whether a tip goes under an answer, which one, and how it reaches the reader.

The work runs in three steps, so no network call ever holds the lock on the reader's settings row:

1. Under the lock: count this interaction and run the cheap gates (opt-out, the number of earlier
   interactions, the daily limit).
2. Without the lock: run the feature checks. Some of them check a feature flag over the network.
3. Under the lock again: record what the checks found and hold today's tip slot.

Then, with two or more candidates, the decision model picks one, and the tip posts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event, slack_distinct_id
from products.slack_app.backend.logic.feature_tips.catalog import CATALOG, TipContext, TipFeature
from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.backend.logic.feature_tips.picker import choose_tip
from products.slack_app.backend.logic.feature_tips.state import FeatureTipsState, mark_shown, parse_state
from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping
from products.slack_app.backend.services.slack_messages import post_slack_ephemeral, section_block
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

# A first-time reader gets answers before any tip, so the tip does not crowd their first impression.
MIN_INTERACTIONS = 3
TIP_INTERVAL = timedelta(hours=24)

FEATURE_TIP_CTA_ACTION_ID = "slack_app_feature_tip_cta"
FEATURE_TIP_DISMISS_ACTION_ID = "slack_app_feature_tip_dismiss"
FEATURE_TIP_OPT_OUT_ACTION_ID = "slack_app_feature_tip_opt_out"
FEATURE_TIP_ACTION_IDS = frozenset(
    {FEATURE_TIP_CTA_ACTION_ID, FEATURE_TIP_DISMISS_ACTION_ID, FEATURE_TIP_OPT_OUT_ACTION_ID}
)


@frozen
class TipRequest:
    integration: WorkspaceIntegration
    slack_user_id: str
    posthog_user: User | None
    channel: str
    thread_ts: str
    person_message: str | None = None
    trace_id: str | None = None


@frozen(slots=False)
class _Reservation:
    candidates: list[TipFeature]
    ctx: TipContext
    interaction_count: int


def offer_feature_tip(request: TipRequest) -> SlackFeature | None:
    integration = request.integration
    stored = list(
        SlackSettings.objects.filter(
            slack_workspace_id=integration.integration_id, slack_user_id=request.slack_user_id
        ).values_list("feature_tips", flat=True)[:1]
    )
    # Most answers come from a reader who opted out or already got today's tip. They stop here,
    # before the lock. Their interaction count no longer gates anything.
    if stored and _skip_without_counting(parse_state(stored[0]), timezone.now()):
        return None
    distinct_id = (
        request.posthog_user.distinct_id
        if request.posthog_user is not None and request.posthog_user.distinct_id
        else slack_distinct_id(integration, request.slack_user_id)
    )
    if not stored:
        SlackSettings.objects.get_or_create(
            slack_workspace_id=integration.integration_id, slack_user_id=request.slack_user_id
        )
    # Counted before the lock, so a reader with a long thread history never holds the row during the scan.
    history_count = (
        _thread_count(integration.integration_id, request.slack_user_id)
        if not stored or parse_state(stored[0]).backfilled_at is None
        else None
    )
    reservation = _reserve_candidates(request, history_count)
    if reservation is None:
        return None
    choice = choose_tip(
        reservation.candidates,
        request.person_message,
        team_id=integration.team_id,
        distinct_id=distinct_id,
        trace_id=request.trace_id,
    )
    if choice is None:
        return None
    tip = CATALOG[choice.feature]
    body = tip.render_text(reservation.ctx)
    try:
        post_slack_ephemeral(
            SlackIntegration(integration).client,
            channel=request.channel,
            user=request.slack_user_id,
            thread_ts=request.thread_ts,
            text=f"💡 Tip: {tip.title}. {body}",
            blocks=tip_blocks(integration.id, tip, reservation.ctx, body),
        )
    except Exception:
        logger.warning("slack_app_feature_tip_post_failed", feature=choice.feature, exc_info=True)
        return None
    mark_shown(integration.integration_id, request.slack_user_id, choice.feature.value, "tip")
    capture_slack_event(
        integration,
        "slack app feature tip shown",
        slack_user_id=request.slack_user_id,
        posthog_user=request.posthog_user,
        feature=choice.feature.value,
        pick_source=choice.source,
        pick_confidence=choice.confidence,
        candidate_count=len(reservation.candidates),
        interaction_count=reservation.interaction_count,
        in_direct_message=reservation.ctx.in_direct_message,
    )
    return choice.feature


def _skip_without_counting(state: FeatureTipsState, now: datetime) -> bool:
    if state.opted_out_at is not None:
        return True
    return (
        state.interaction_count >= MIN_INTERACTIONS
        and state.last_shown_at is not None
        and now - state.last_shown_at < TIP_INTERVAL
    )


def _is_due(state: FeatureTipsState, now: datetime) -> bool:
    return (
        state.opted_out_at is None
        and state.interaction_count >= MIN_INTERACTIONS
        and (state.last_shown_at is None or now - state.last_shown_at >= TIP_INTERVAL)
    )


def _locked_settings(workspace_id: str, slack_user_id: str) -> SlackSettings | None:
    # Another answer for this reader holds the row when this returns None. That answer decides about today's tip.
    return (
        SlackSettings.objects.filter(slack_workspace_id=workspace_id, slack_user_id=slack_user_id)
        .select_for_update(skip_locked=True)
        .first()
    )


def _save(settings: SlackSettings, state: FeatureTipsState) -> None:
    settings.feature_tips = state.model_dump(mode="json")
    settings.save(update_fields=["feature_tips", "updated_at"])


def _thread_count(workspace_id: str, slack_user_id: str) -> int:
    return SlackThreadTaskMapping.objects.filter(
        slack_workspace_id=workspace_id, mentioning_slack_user_id=slack_user_id
    ).count()


def _reserve_candidates(request: TipRequest, history_count: int | None) -> _Reservation | None:
    """Count this interaction, run the gates and the feature checks, and hold today's tip slot.

    The slot is held before the tip posts, so two answers that finish together cannot both send
    one. A post that then fails gives up the tip for that day, which is the cheaper mistake.
    """
    workspace_id = request.integration.integration_id
    slack_user_id = request.slack_user_id
    now = timezone.now()

    with transaction.atomic():
        settings = _locked_settings(workspace_id, slack_user_id)
        if settings is None:
            return None
        state = parse_state(settings.feature_tips)
        if state.backfilled_at is None:
            # The history already holds the thread of this answer, so it is not counted again.
            state.interaction_count = (
                history_count if history_count is not None else _thread_count(workspace_id, slack_user_id)
            )
            state.backfilled_at = now
        else:
            state.interaction_count += 1
        _save(settings, state)
    if not _is_due(state, now):
        return None

    ctx = TipContext(
        integration=request.integration,
        slack_user_id=slack_user_id,
        posthog_user_id=request.posthog_user.id if request.posthog_user is not None else None,
        channel=request.channel,
        settings=settings,
    )
    newly_used: list[SlackFeature] = []
    candidates: list[TipFeature] = []
    for feature, tip in CATALOG.items():
        if feature.value in state.used or feature.value in state.shown:
            continue
        if tip.was_used(ctx):
            newly_used.append(feature)
        elif tip.is_eligible(ctx):
            candidates.append(tip)

    with transaction.atomic():
        settings = _locked_settings(workspace_id, slack_user_id)
        if settings is None:
            return None
        state = parse_state(settings.feature_tips)
        for feature in newly_used:
            state.used.setdefault(feature.value, now)
        # A tip that another answer sent while the checks ran is already counted. Do not send a second one.
        candidates = [tip for tip in candidates if tip.feature.value not in state.shown]
        reserved = bool(candidates) and _is_due(state, now)
        if reserved:
            state.last_shown_at = now
        _save(settings, state)
    if not reserved:
        return None
    return _Reservation(candidates=candidates, ctx=ctx, interaction_count=state.interaction_count)


def _button(action_id: str, label: str, value: str, **extra: str) -> dict[str, Any]:
    return {
        "type": "button",
        "action_id": action_id,
        "text": {"type": "plain_text", "text": label},
        "value": value,
        **extra,
    }


def tip_blocks(integration_id: int, tip: TipFeature, ctx: TipContext, body: str) -> list[dict[str, Any]]:
    # The integration id lets the cross-region interactivity router find the region that owns the click.
    value = json.dumps({"integration_id": integration_id, "feature": tip.feature.value})
    buttons: list[dict[str, Any]] = []
    cta = tip.cta(ctx)
    if cta is not None:
        extra = {"style": "primary", **({"url": cta.url} if cta.url else {})}
        buttons.append(_button(FEATURE_TIP_CTA_ACTION_ID, cta.label, value, **extra))
    buttons.append(_button(FEATURE_TIP_DISMISS_ACTION_ID, "Not now", value))
    buttons.append(_button(FEATURE_TIP_OPT_OUT_ACTION_ID, "Don't show tips", value))
    return [
        section_block(f"💡 *Tip: {tip.title}*\n{tip.emoji} {body}"),
        {"type": "actions", "elements": buttons},
    ]
