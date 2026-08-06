"""Lifecycle telemetry for Replay Vision alerts and digests (VisionActions).

Event names track the user-facing nouns rather than the model enum: `mode=alert` actions report as
`replay_vision_alert_*`, everything else as `replay_vision_digest_*`. Every event carries
`organization_id` as an event property because org-level analyses join on it. The helpers live here
(not in api/vision_actions.py) so api/scanners.py can report the auto-provisioned scanner digest
without importing another API module.
"""

from typing import TYPE_CHECKING, Any

from products.replay_vision.backend.models.vision_action import ActionMode, VisionAction

if TYPE_CHECKING:
    from posthog.models import Team


def vision_action_noun(action: VisionAction) -> str:
    return "alert" if action.mode == ActionMode.ALERT else "digest"


def vision_action_lifecycle_properties(action: VisionAction, team: "Team") -> dict[str, Any]:
    """Config choices at save time, mirroring `_scanner_lifecycle_properties` in api/scanners.py.
    Destination addresses (Slack channels, webhook URLs) stay out: they can carry customer data."""
    delivery = action.delivery_config if isinstance(action.delivery_config, list) else []
    destination_types = [target.get("type") for target in delivery if isinstance(target, dict)]
    properties: dict[str, Any] = {
        "vision_action_id": str(action.id),
        "scanner_id": str(action.scanner_id) if action.scanner_id else None,
        "mode": action.mode,
        "enabled": action.enabled,
        "is_scanner_digest": action.is_scanner_digest,
        "destination_type": destination_types[0] if destination_types else None,
        "destination_types": destination_types,
        "team_id": team.id,
        "organization_id": str(team.organization_id),
    }
    if action.mode == ActionMode.ALERT:
        alert_config = action.alert_config if isinstance(action.alert_config, dict) else {}
        properties.update(
            {
                "alert_frequency": alert_config.get("frequency"),
                "alert_metric": alert_config.get("metric"),
                "alert_threshold": alert_config.get("threshold"),
                "alert_direction": alert_config.get("direction"),
                "alert_window_days": alert_config.get("window_days"),
            }
        )
    else:
        trigger_config = action.trigger_config if isinstance(action.trigger_config, dict) else {}
        properties.update(
            {
                "rrule": trigger_config.get("rrule"),
                "timezone": trigger_config.get("timezone"),
            }
        )
    return properties
