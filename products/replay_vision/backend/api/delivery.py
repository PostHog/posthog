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


def _slack_destination_payload(action: VisionAction, target: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": _INTERNAL_DESTINATION,
        "enabled": action.enabled,
        "template_id": _SLACK_TEMPLATE,
        "name": f"Replay Vision · {action.name}",
        "filters": {
            "events": [{"id": EVENT_NAME, "type": "events"}],
            "properties": [
                {"key": "vision_action_id", "value": str(action.id), "operator": "exact", "type": "event"},
            ],
        },
        "inputs": {
            "slack_workspace": {"value": target["integration_id"]},
            "channel": {"value": _channel_id(target["channel"])},
            # Hog-templated pass-through of the pre-formatted Slack text carried on the event.
            "text": {"value": "{event.properties.slack_text}"},
        },
    }


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
        serializer = HogFunctionSerializer(data=_slack_destination_payload(action, target), context=context)
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
