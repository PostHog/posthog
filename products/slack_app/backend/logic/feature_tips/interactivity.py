"""What a click on a tip's buttons does. Only the reader sees the tip, so the clicker is the reader."""

from __future__ import annotations

import json
from typing import Any

from django.http import HttpResponse
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.feature_tips.catalog import CATALOG
from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.backend.logic.feature_tips.offer import (
    FEATURE_TIP_ACTION_IDS,
    FEATURE_TIP_CTA_ACTION_ID,
    FEATURE_TIP_DISMISS_ACTION_ID,
    FEATURE_TIP_OPT_OUT_ACTION_ID,
)
from products.slack_app.backend.logic.feature_tips.state import FeatureTipsState, TipRecord, update_state
from products.slack_app.backend.services.inbox_interactivity import post_response_url
from products.slack_app.backend.services.workspace_integrations import get_workspace_integration

logger = structlog.get_logger(__name__)

TIPS_OFF_TEXT = "👋 Got it. I won't show you more tips."


@frozen
class _TipClick:
    action_id: str
    value: dict[str, Any]


def _tip_action(payload: dict[str, Any]) -> _TipClick | None:
    for action in payload.get("actions", []):
        if action.get("action_id") not in FEATURE_TIP_ACTION_IDS:
            continue
        try:
            value = json.loads(action.get("value") or "")
        except json.JSONDecodeError:
            return None
        if isinstance(value, dict):
            return _TipClick(action_id=action["action_id"], value=value)
    return None


def is_feature_tip_action(action_id: object) -> bool:
    return action_id in FEATURE_TIP_ACTION_IDS


def _integration_id(value: dict[str, Any]) -> int | None:
    integration_id = value.get("integration_id")
    return integration_id if isinstance(integration_id, int) else None


def feature_tip_integration_hint(payload: dict[str, Any]) -> int | None:
    found = _tip_action(payload)
    return _integration_id(found.value) if found is not None else None


def handle_feature_tip_action(payload: dict[str, Any]) -> HttpResponse:
    response_url = payload.get("response_url", "")
    found = _tip_action(payload)
    integration_id = _integration_id(found.value) if found is not None else None
    slack_user_id = payload.get("user", {}).get("id")
    slack_team_id = payload.get("team", {}).get("id")
    if found is None or integration_id is None or not slack_user_id or not slack_team_id:
        post_response_url(response_url, {"delete_original": True})
        return HttpResponse(status=200)
    value = found.value
    integration = get_workspace_integration(integration_id, slack_team_id)
    if integration is None or value.get("feature") not in SlackFeature:
        post_response_url(response_url, {"delete_original": True})
        return HttpResponse(status=200)
    feature = SlackFeature(value["feature"])

    action_id = found.action_id
    tip = CATALOG[feature]
    runs_action = action_id == FEATURE_TIP_CTA_ACTION_ID and tip.has_action
    now = timezone.now()

    def change(state: FeatureTipsState) -> None:
        record = state.shown.setdefault(feature.value, TipRecord(first_shown_at=now))
        if action_id == FEATURE_TIP_CTA_ACTION_ID:
            record.clicked_at = now
        elif action_id == FEATURE_TIP_DISMISS_ACTION_ID:
            record.dismissed_at = now
        elif action_id == FEATURE_TIP_OPT_OUT_ACTION_ID:
            record.dismissed_at = now
            state.opted_out_at = now
        if runs_action:
            state.used.setdefault(feature.value, now)

    update_state(integration.integration_id, slack_user_id, change)

    if action_id == FEATURE_TIP_CTA_ACTION_ID:
        event = "slack app feature tip clicked"
        if runs_action:
            text = tip.apply_action(integration, slack_user_id)
            post_response_url(response_url, {"replace_original": True, "text": text})
        else:
            post_response_url(response_url, {"delete_original": True})
    elif action_id == FEATURE_TIP_OPT_OUT_ACTION_ID:
        event = "slack app feature tips turned off"
        post_response_url(response_url, {"replace_original": True, "text": TIPS_OFF_TEXT})
    else:
        event = "slack app feature tip dismissed"
        post_response_url(response_url, {"delete_original": True})
    capture_slack_event(integration, event, slack_user_id=slack_user_id, feature=feature.value)
    return HttpResponse(status=200)
