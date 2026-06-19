from typing import Any

import structlog
from rest_framework.request import Request

from posthog.models import Team

from products.replay_vision.backend.models.vision_action import VisionAction
from products.workflows.backend.api.hog_flow import HogFlowSerializer
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

logger = structlog.get_logger(__name__)

# The scheduled child of a vision action captures this event with `vision_action_id` and `slack_text`
# properties; the delivery flow triggers on it (filtered to one action) and posts `slack_text` to Slack.
EVENT_NAME = "$replay_vision_action_ready"


def _serializer_context(*, request: Request, team: Team) -> dict[str, Any]:
    return {"request": request, "team_id": team.id, "get_team": lambda: team}


def build_flow_payload(action: VisionAction) -> dict[str, Any]:
    """Build the writable HogFlowSerializer payload that delivers this action's summary to Slack.

    Graph: trigger (filtered to this action's event) -> one function node per Slack target -> exit,
    chained with continue edges.
    """
    trigger_node = {
        "id": "trigger_node",
        "name": "trigger",
        "type": "trigger",
        "config": {
            "type": "event",
            "filters": {
                "events": [
                    {
                        "id": EVENT_NAME,
                        "name": EVENT_NAME,
                        "type": "events",
                        "order": 0,
                        "properties": [
                            {
                                "key": "vision_action_id",
                                "type": "event",
                                "value": [str(action.id)],
                                "operator": "exact",
                            }
                        ],
                    }
                ]
            },
        },
    }

    slack_nodes = [
        {
            "id": f"slack_{i}",
            "name": f"Slack {i}",
            "type": "function",
            "config": {
                "template_id": "template-slack",
                "inputs": {
                    "slack_workspace": {"value": target["integration_id"], "order": 0},
                    "channel": {"value": target["channel"]},
                    "text": {"value": "{event.properties.slack_text}"},
                },
            },
        }
        for i, target in enumerate(action.delivery_config)
    ]

    exit_node = {"id": "exit_node", "name": "exit", "type": "exit", "config": {}}

    actions = [trigger_node, *slack_nodes, exit_node]

    # Chain trigger -> slack_0 -> ... -> exit_node with continue edges.
    edges = [
        {"from": actions[i]["id"], "to": actions[i + 1]["id"], "type": "continue"} for i in range(len(actions) - 1)
    ]

    return {
        "name": f"Replay Vision · {action.name}",
        "status": "active" if action.enabled else "archived",
        "actions": actions,
        "edges": edges,
    }


def provision_delivery_flow(action: VisionAction, *, request: Request, team: Team) -> None:
    """Create or update the delivery HogFlow for this action.

    With no delivery targets there's nothing to deliver: archive any existing flow, else no-op. A flow
    save failure propagates so the caller learns delivery wasn't wired up.
    """
    if not action.delivery_config:
        if action.hog_flow_id:
            archive_delivery_flow(action, request=request, team=team)
        return

    context = _serializer_context(request=request, team=team)
    payload = build_flow_payload(action)

    serializer = HogFlowSerializer(data=payload, context=context)
    if action.hog_flow_id:
        try:
            # Update the existing flow in place; fall through to a fresh one if it was deleted
            # out of band (a stale hog_flow_id must not fail the action update).
            flow = HogFlow.objects.get(id=action.hog_flow_id, team=team)
            serializer = HogFlowSerializer(flow, data=payload, context=context)
        except HogFlow.DoesNotExist:
            pass

    serializer.is_valid(raise_exception=True)
    flow = serializer.save()

    if action.hog_flow_id != flow.id:
        action.hog_flow = flow
        action.save(update_fields=["hog_flow", "updated_at"])


def archive_delivery_flow(action: VisionAction, *, request: Request, team: Team) -> None:
    """Best-effort archive of the action's delivery flow — a failure here never blocks the action delete."""
    if not action.hog_flow_id:
        return
    try:
        flow = HogFlow.objects.get(id=action.hog_flow_id, team=team)
        context = _serializer_context(request=request, team=team)
        serializer = HogFlowSerializer(flow, data={"status": "archived"}, partial=True, context=context)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    except Exception:
        logger.exception("replay_vision_delivery_flow_archive_failed", vision_action_id=str(action.id))
