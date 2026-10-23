"""Whether a tip goes under an answer, which one, and how it reaches the reader.

The cheap checks run first, under a lock on the reader's settings row: opt-out, the number of
earlier interactions, and the daily limit. Only a reader who passes them gets the feature checks
and, with two or more candidates, the decision model call. The call runs after the lock is
released, so a slow model never holds the row.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import Integration, SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event, slack_distinct_id
from products.slack_app.backend.feature_flags import is_slack_app_feature_tips_enabled
from products.slack_app.backend.logic.feature_tips.catalog import CATALOG, SlackFeature, TipContext, TipFeature
from products.slack_app.backend.logic.feature_tips.picker import choose_tip
from products.slack_app.backend.logic.feature_tips.state import mark_shown, parse_state
from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping
from products.slack_app.backend.services.slack_messages import post_slack_ephemeral, section_block

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
    integration: Integration
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
    """Post one tip under the answer the reader just got, if one is due. Returns the feature it promoted."""
    integration = request.integration
    distinct_id = (
        request.posthog_user.distinct_id
        if request.posthog_user is not None and request.posthog_user.distinct_id
        else slack_distinct_id(integration, request.slack_user_id)
    )
    if not is_slack_app_feature_tips_enabled(integration, distinct_id):
        return None
    reservation = _reserve_candidates(request)
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
    try:
        post_slack_ephemeral(
            SlackIntegration(integration).client,
            channel=request.channel,
            user=request.slack_user_id,
            thread_ts=request.thread_ts,
            text=tip.text,
            blocks=tip_blocks(integration.id, tip, reservation.ctx),
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


def _reserve_candidates(request: TipRequest) -> _Reservation | None:
    """Count this interaction, run the gates, and hold today's tip slot when a tip is due.

    The slot is held before the tip posts, so two answers that finish together cannot both send
    one. A post that then fails gives up the tip for that day, which is the cheaper mistake.
    """
    workspace_id = request.integration.integration_id
    SlackSettings.objects.get_or_create(slack_workspace_id=workspace_id, slack_user_id=request.slack_user_id)
    now = timezone.now()
    with transaction.atomic():
        settings = (
            SlackSettings.objects.filter(slack_workspace_id=workspace_id, slack_user_id=request.slack_user_id)
            .select_for_update(skip_locked=True)
            .first()
        )
        # Another answer for this reader holds the row. That answer decides about today's tip.
        if settings is None:
            return None
        state = parse_state(settings.feature_tips)
        if state.backfilled_at is None:
            # The history already holds the thread of this answer, so it is not counted again.
            state.interaction_count = SlackThreadTaskMapping.objects.filter(
                slack_workspace_id=workspace_id, mentioning_slack_user_id=request.slack_user_id
            ).count()
            state.backfilled_at = now
        else:
            state.interaction_count += 1

        candidates: list[TipFeature] = []
        ctx = TipContext(
            integration=request.integration,
            slack_user_id=request.slack_user_id,
            posthog_user_id=request.posthog_user.id if request.posthog_user is not None else None,
            channel=request.channel,
            settings=settings,
        )
        due = (
            state.opted_out_at is None
            and state.interaction_count >= MIN_INTERACTIONS
            and (state.last_shown_at is None or now - state.last_shown_at >= TIP_INTERVAL)
        )
        if due:
            for feature, tip in CATALOG.items():
                if feature.value in state.used or feature.value in state.shown:
                    continue
                if tip.was_used(ctx):
                    state.used[feature.value] = now
                elif tip.is_eligible(ctx):
                    candidates.append(tip)
            if candidates:
                state.last_shown_at = now
        settings.feature_tips = state.model_dump(mode="json")
        settings.save(update_fields=["feature_tips", "updated_at"])
    if not candidates:
        return None
    return _Reservation(candidates=candidates, ctx=ctx, interaction_count=state.interaction_count)


def tip_blocks(integration_id: int, tip: TipFeature, ctx: TipContext) -> list[dict[str, Any]]:
    # The integration id lets the cross-region interactivity router find the region that owns the click.
    value = json.dumps({"integration_id": integration_id, "feature": tip.feature.value})
    buttons: list[dict[str, Any]] = []
    cta = tip.cta(ctx)
    if cta is not None:
        button: dict[str, Any] = {
            "type": "button",
            "action_id": FEATURE_TIP_CTA_ACTION_ID,
            "text": {"type": "plain_text", "text": cta.label},
            "style": "primary",
            "value": value,
        }
        if cta.url:
            button["url"] = cta.url
        buttons.append(button)
    buttons.append(
        {
            "type": "button",
            "action_id": FEATURE_TIP_DISMISS_ACTION_ID,
            "text": {"type": "plain_text", "text": "Not now"},
            "value": value,
        }
    )
    buttons.append(
        {
            "type": "button",
            "action_id": FEATURE_TIP_OPT_OUT_ACTION_ID,
            "text": {"type": "plain_text", "text": "Don't show tips"},
            "value": value,
        }
    )
    return [section_block(tip.text), {"type": "actions", "elements": buttons}]
