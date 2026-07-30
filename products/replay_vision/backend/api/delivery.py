from typing import Any

from django.db.models import QuerySet

import structlog
from rest_framework.request import Request

from posthog.models import Team

from products.cdp.backend.api.hog_function import HogFunctionSerializer
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.replay_vision.backend.models.vision_action import VisionAction

logger = structlog.get_logger(__name__)

# The scheduled child of a vision action emits this as a PRIVATE internal event (cdp_internal_events
# topic) with `vision_action_id` + `slack_text`. Per-action `internal_destination` HogFunctions filter
# on it and post `slack_text` to their channel. Using the internal channel (not the public capture
# pipeline) makes the trigger non-forgeable with the project's client token — the Alerts pattern.
EVENT_NAME = "$replay_vision_action_ready"
_INTERNAL_DESTINATION = "internal_destination"
_SLACK_TEMPLATE = "template-slack"
_WEBHOOK_TEMPLATE = "template-webhook"

# Marks our webhook payloads so a consumer can pin the schema and we can evolve it without breaking them.
# Mirrors the alerts/logs destination convention (products/alerts/backend/destination_configs.py).
_WEBHOOK_HEADERS = {"Content-Type": "application/json", "X-PostHog-Webhook-Version": "1"}


def _managed_destinations(action: VisionAction, team: Team) -> QuerySet[HogFunction]:
    """The internal_destination HogFunctions this action owns.

    There's no FK on the action — the trigger filter IS the binding, so we find them by the
    `vision_action_id` property the filter carries (the same bind-by-filter pattern alerts use).
    """
    return HogFunction.objects.filter(
        team_id=team.id,
        type=_INTERNAL_DESTINATION,
        deleted=False,
        filters__contains={"properties": [{"key": "vision_action_id", "value": str(action.id)}]},
    )


def _channel_id(value: str) -> str:
    # The channel is stored as the `${id}|#${name}` picker composite so the UI can show a friendly
    # name; the Slack template wants the bare id. Mirrors `slackChannelId` in the frontend.
    return value.split("|", 1)[0].strip()


def _base_destination_payload(action: VisionAction, template_id: str) -> dict[str, Any]:
    """The internal_destination scaffold every delivery type shares: the trigger filter that binds the
    destination to this action, plus its enabled state. Callers fill in `inputs` per template."""
    return {
        "type": _INTERNAL_DESTINATION,
        "enabled": action.enabled,
        "template_id": template_id,
        "name": f"Replay Vision · {action.name}",
        "filters": {
            "events": [{"id": EVENT_NAME, "type": "events"}],
            "properties": [
                {"key": "vision_action_id", "value": str(action.id), "operator": "exact", "type": "event"},
            ],
        },
    }


def _slack_destination_payload(action: VisionAction, target: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base_destination_payload(action, _SLACK_TEMPLATE),
        "inputs": {
            "slack_workspace": {"value": target["integration_id"]},
            "channel": {"value": _channel_id(target["channel"])},
            # Pre-split section blocks carried on the event: a whole-string template on a json input
            # resolves to the raw list, so the full report renders as ONE message (Slack never splits
            # blocks, while `text` over ~4k gets split at arbitrary positions, cutting links in half).
            "blocks": {"value": "{event.properties.slack_blocks}"},
            # Fallback + notification preview when blocks are present or missing (pre-blocks runs).
            "text": {"value": "{event.properties.slack_text}"},
        },
    }


def _webhook_destination_payload(action: VisionAction, target: dict[str, Any]) -> dict[str, Any]:
    # A structured JSON envelope (not the Slack-formatted text) so machine consumers get clean fields.
    # `type` routes on the event kind (digest / alert_fired / alert_recovered); `data` carries the report
    # plus the run link. Template strings resolve against the emitted event's properties at delivery time.
    body = {
        "id": "{event.uuid}",
        "type": "replay_vision.{event.properties.event_kind}",
        "timestamp": "{event.properties.emitted_at}",
        "data": {
            "vision_action_id": "{event.properties.vision_action_id}",
            "run_id": "{event.properties.vision_action_run_id}",
            "scanner_id": "{event.properties.scanner_id}",
            "action_name": "{event.properties.action_name}",
            "scanner_name": "{event.properties.scanner_name}",
            "observation_count": "{event.properties.observation_count}",
            "report": "{event.properties.report_markdown}",
            "run_url": "{event.properties.run_url}",
        },
    }
    return {
        **_base_destination_payload(action, _WEBHOOK_TEMPLATE),
        "inputs": {
            "url": {"value": target["url"]},
            "method": {"value": "POST"},
            "headers": {"value": _WEBHOOK_HEADERS},
            "body": {"value": body},
        },
    }


def _destination_payload(action: VisionAction, target: dict[str, Any]) -> dict[str, Any]:
    if target.get("type") == "webhook":
        return _webhook_destination_payload(action, target)
    return _slack_destination_payload(action, target)


def provision_delivery(action: VisionAction, *, request: Request, team: Team) -> None:
    """Reconcile this action's `internal_destination` HogFunctions to its `delivery_config`.

    Archive-and-recreate: drop the action's managed destinations, then create one per delivery target
    when the action is enabled. A provisioning failure propagates so the caller learns delivery wasn't
    wired up — the viewset runs this inside its atomic block.
    """
    _archive_managed(action, team)
    if not action.enabled or not action.delivery_config:
        return

    # HogFunctionSerializer.create() reads context["request"].user, so provisioning stays in the viewset.
    context = {"request": request, "team_id": team.id, "get_team": lambda: team, "is_create": True}
    for target in action.delivery_config:
        serializer = HogFunctionSerializer(data=_destination_payload(action, target), context=context)
        serializer.is_valid(raise_exception=True)
        serializer.save()


def archive_delivery(action: VisionAction, *, team: Team) -> None:
    """Best-effort archive of the action's delivery destinations — a failure never blocks the delete."""
    try:
        _archive_managed(action, team)
    except Exception:
        logger.exception("replay_vision_delivery_archive_failed", vision_action_id=str(action.id))


def _archive_managed(action: VisionAction, team: Team) -> None:
    # Per-row .save() (not a bulk .update()) so the post_save signal deregisters each function from the
    # workers — a soft-deleted destination must stop firing.
    for fn in _managed_destinations(action, team):
        fn.enabled = False
        fn.deleted = True
        fn.save()
