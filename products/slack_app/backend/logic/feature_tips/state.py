"""What one Slack user did with the Slack app features: used them, saw a tip, or dismissed it.

The state lives in ``SlackSettings.feature_tips`` on the user's personal row, so it exists before
the user links a PostHog account.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from django.db import transaction
from django.utils import timezone

import structlog
from pydantic import BaseModel, ValidationError

from products.slack_app.backend.models import SlackSettings

logger = structlog.get_logger(__name__)

TipSource = Literal["tip", "onboarding"]


class TipRecord(BaseModel):
    first_shown_at: datetime
    times_shown: int = 1
    source: TipSource = "tip"
    clicked_at: datetime | None = None
    dismissed_at: datetime | None = None


class FeatureTipsState(BaseModel):
    version: int = 1
    backfilled_at: datetime | None = None
    interaction_count: int = 0
    # Keys are ``SlackFeature`` values. Plain strings, so a feature removed from the catalog
    # does not make the stored state fail to parse.
    used: dict[str, datetime] = {}
    shown: dict[str, TipRecord] = {}
    opted_out_at: datetime | None = None
    last_shown_at: datetime | None = None


def parse_state(raw: object) -> FeatureTipsState:
    if not raw:
        return FeatureTipsState()
    try:
        return FeatureTipsState.model_validate(raw)
    except ValidationError:
        # A broken row must not block tips forever. Starting again shows a tip at most once more.
        logger.warning("slack_app_feature_tips_state_invalid")
        return FeatureTipsState()


def get_state(slack_workspace_id: str, slack_user_id: str) -> FeatureTipsState:
    raw = (
        SlackSettings.objects.filter(slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id)
        .values_list("feature_tips", flat=True)
        .first()
    )
    return parse_state(raw)


def update_state(
    slack_workspace_id: str, slack_user_id: str, change: Callable[[FeatureTipsState], None]
) -> FeatureTipsState:
    """Apply ``change`` to the stored state under a row lock, so two writers never lose an update.

    The lock is on the user's own settings row. Keep ``change`` free of network calls, because
    the row stays locked until it returns.
    """
    with transaction.atomic():
        settings, _ = SlackSettings.objects.select_for_update().get_or_create(
            slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id
        )
        state = parse_state(settings.feature_tips)
        change(state)
        settings.feature_tips = state.model_dump(mode="json")
        settings.save(update_fields=["feature_tips", "updated_at"])
    return state


def mark_used(slack_workspace_id: str, slack_user_id: str, feature: str) -> None:
    def change(state: FeatureTipsState) -> None:
        state.used.setdefault(feature, timezone.now())

    update_state(slack_workspace_id, slack_user_id, change)


def record_feature_used(slack_workspace_id: str, slack_user_id: str | None, feature: str) -> None:
    """Never raises, because it runs inside the code path of the feature itself.

    Checks the key in SQL first, so a feature used every day costs one indexed read after its first
    use, not a locked write.
    """
    if not slack_user_id:
        return
    try:
        if SlackSettings.objects.filter(
            slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id, feature_tips__used__has_key=feature
        ).exists():
            return
        mark_used(slack_workspace_id, slack_user_id, feature)
    except Exception:
        logger.warning("slack_app_feature_tips_record_used_failed", feature=feature, exc_info=True)


def mark_shown(slack_workspace_id: str, slack_user_id: str, feature: str, source: TipSource) -> None:
    def change(state: FeatureTipsState) -> None:
        record_shown(state, feature, source, timezone.now())

    update_state(slack_workspace_id, slack_user_id, change)


def record_shown(state: FeatureTipsState, feature: str, source: TipSource, now: datetime) -> None:
    record = state.shown.get(feature)
    if record is None:
        state.shown[feature] = TipRecord(first_shown_at=now, source=source)
    else:
        record.times_shown += 1
    if source == "tip":
        state.last_shown_at = now
