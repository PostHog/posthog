"""The insight alerts a workflow's `$insight_alert_firing` trigger names."""

import uuid
from typing import Any

from products.cdp.backend.internal_events import LEGACY_INSIGHT_ALERT_EVENT
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

INSIGHT_ALERT_FIRING_EVENT = LEGACY_INSIGHT_ALERT_EVENT


def _alert_id_filters(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Every exact `alert_id` event filter in the global properties.

    The compiler ANDs global properties with every event entry, but ORs the entries together, so a
    filter on one entry does not restrict another entry for the same event.
    """
    properties = filters.get("properties")
    # Only an exact event-property filter restricts which events match. Another type, such as a
    # person filter, compiles to a condition that does not read the event's alert id at all.
    return [
        prop
        for prop in (properties if isinstance(properties, list) else [])
        if isinstance(prop, dict)
        and prop.get("key") == "alert_id"
        and prop.get("type") == "event"
        and (prop.get("operator") or "exact") == "exact"
    ]


def trigger_alert_ids(filters: dict[str, Any]) -> list[str]:
    """The alert ids the trigger's exact `alert_id` filters name, as given."""
    ids: list[str] = []
    for prop in _alert_id_filters(filters):
        value = prop.get("value")
        ids.extend(str(item) for item in (value if isinstance(value, list) else [value]) if item not in (None, ""))
    return ids


def normalize_alert_id_filters(filters: dict[str, Any]) -> None:
    """Write each named alert id in canonical form in place, to match the lowercase id the event carries."""
    for prop in _alert_id_filters(filters):
        value = prop.get("value")
        items = value if isinstance(value, list) else [value]
        try:
            prop["value"] = [str(uuid.UUID(str(item))) for item in items if item not in (None, "")]
        except ValueError:
            # The access check refuses an id that is not a UUID with a message the person can act on.
            continue


def alert_ids_with_live_workflows(team_id: int) -> frozenset[str]:
    """The team's insight alerts that an active workflow starts on."""
    triggers = HogFlow.objects.filter(
        team_id=team_id, status=HogFlow.State.ACTIVE, trigger__type="internal-event"
    ).values_list("trigger", flat=True)
    ids: set[str] = set()
    for trigger in triggers:
        filters = trigger.get("filters") if isinstance(trigger, dict) else None
        if not isinstance(filters, dict):
            continue
        events = filters.get("events")
        if isinstance(events, list) and any(
            isinstance(event, dict) and event.get("id") == INSIGHT_ALERT_FIRING_EVENT for event in events
        ):
            ids.update(trigger_alert_ids(filters))
    return frozenset(ids)
