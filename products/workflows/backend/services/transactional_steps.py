"""Which workflows may hold transactional steps. Usage reports count a send as transactional by its step id, so only
the workflows the transactional send APIs make may use those ids, and other workflows can't add transactional email."""

from typing import Any, Final

from products.workflows.backend.facade.contracts import TRANSACTIONAL_EMAIL_ACTION_ID, TRANSACTIONAL_PUSH_ACTION_ID
from products.workflows.backend.facade.enums import HogFlowOriginProduct
from products.workflows.backend.models.hog_flow.hog_flow import SANDBOX_EMAIL_ACTION_TYPE

TRANSACTIONAL_STEPS: Final[dict[str, tuple[str, str]]] = {
    HogFlowOriginProduct.TRANSACTIONAL_EMAILS: (TRANSACTIONAL_EMAIL_ACTION_ID, "function_email"),
    HogFlowOriginProduct.TRANSACTIONAL_EMAIL_KEYS: (TRANSACTIONAL_EMAIL_ACTION_ID, "function_email"),
    HogFlowOriginProduct.TRANSACTIONAL_PUSH: (TRANSACTIONAL_PUSH_ACTION_ID, "function_push"),
}
RESERVED_STEP_IDS: Final[frozenset[str]] = frozenset({TRANSACTIONAL_EMAIL_ACTION_ID, TRANSACTIONAL_PUSH_ACTION_ID})
EMAIL_STEP_TYPES: Final[frozenset[str]] = frozenset({"function_email", SANDBOX_EMAIL_ACTION_TYPE})
# Support replies and ticket updates must reach people who opted out of marketing email. The names of the events the
# support product emits. Keep in step with CONVERSATION_ANALYTICS_EVENTS in products/conversations/backend/events.py
# and SUPPORT_EVENTS in nodejs/src/cdp/services/hogflows/hogflow-quota-limiting.ts.
SUPPORT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "$conversation_ticket_created",
        "$conversation_ticket_status_changed",
        "$conversation_ticket_priority_changed",
        "$conversation_ticket_assigned",
        "$conversation_ticket_tag_added",
        "$conversation_message_sent",
        "$conversation_private_message_sent",
        "$conversation_message_received",
    }
)


def is_transactional_origin(origin_product: str | None) -> bool:
    return origin_product in TRANSACTIONAL_STEPS


def holds_transactional_step(origin_product: str, actions: list[dict[str, Any]]) -> bool:
    step_id, step_type = TRANSACTIONAL_STEPS[origin_product]
    return any(
        isinstance(action, dict) and (action.get("id"), action.get("type")) == (step_id, step_type)
        for action in actions
    )


def keeps_transactional_shape(origin_product: str, actions: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bool:
    """Whether the steps are still the trigger, the one message step, and the exit that the send API runs."""
    step_id, step_type = TRANSACTIONAL_STEPS[origin_product]
    if len(actions) != 3 or not all(isinstance(action, dict) for action in actions):
        return False
    trigger, message, exit_step = (_find(actions, type_) for type_ in ("trigger", step_type, "exit"))
    if trigger is None or message is None or exit_step is None:
        return False
    # The runner follows the edges, so a trigger wired straight to the exit would skip the message.
    path = {(trigger.get("id"), step_id, "continue"), (step_id, exit_step.get("id"), "continue")}
    return (
        (trigger.get("config") or {}).get("type") == "api"
        and message.get("id") == step_id
        and (message.get("config") or {}).get("message_category_type") == "transactional"
        and len(edges) == 2
        and {(edge.get("from"), edge.get("to"), edge.get("type")) for edge in edges if isinstance(edge, dict)} == path
    )


def new_reserved_steps(actions: list[dict[str, Any]], *stored_step_lists: list[dict[str, Any]] | None) -> list[str]:
    """The reserved step ids in `actions` that no stored step of the same type already has."""
    stored = {_reserved_step(step) for steps in stored_step_lists for step in steps or []}
    return sorted({key[0] for action in actions if (key := _reserved_step(action)) and key not in stored})


def _reserved_step(step: Any) -> tuple[str, str] | None:
    if isinstance(step, dict) and step.get("id") in RESERVED_STEP_IDS:
        return (str(step["id"]), str(step.get("type")))
    return None


def added_transactional_email_steps(
    actions: list[dict[str, Any]], *stored_step_lists: list[dict[str, Any]] | None
) -> list[str]:
    """The names of transactional email steps that the stored steps don't already have as transactional email. A
    step stored under a support trigger counts as new, so changing the trigger can't keep it transactional."""
    if _triggers_only_on_support_events(actions):
        return []
    existing = {
        step["id"]
        for steps in stored_step_lists
        if steps and not _triggers_only_on_support_events(steps)
        for step in steps
        if _is_transactional_email(step) and step.get("id")
    }
    return [
        str(action.get("name") or action.get("id"))
        for action in actions
        if _is_transactional_email(action) and action.get("id") not in existing
    ]


def _is_transactional_email(step: Any) -> bool:
    return (
        isinstance(step, dict)
        and step.get("type") in EMAIL_STEP_TYPES
        and (step.get("config") or {}).get("message_category_type") == "transactional"
    )


def _triggers_only_on_support_events(actions: list[dict[str, Any]]) -> bool:
    trigger = _find(actions, "trigger")
    if trigger is None:
        return False
    config = trigger.get("config") or {}
    filters = config.get("filters") if isinstance(config, dict) else None
    # A lenient draft can store any value here.
    if not isinstance(filters, dict):
        return False
    events = filters.get("events")
    if not isinstance(events, list) or not events or filters.get("actions"):
        return False
    if not all(isinstance(event, dict) for event in events):
        return False
    if config.get("type") == "internal-event":
        # The internal event consumer matches the entry's id alone.
        return filters.get("source") == "internal-events" and all(_is_support_event(event) for event in events)
    # The filter compiler matches the event name only on entries of type `events`, so another entry matches any event.
    return config.get("type") == "event" and all(
        event.get("type") == "events" and _is_support_event(event) for event in events
    )


def _is_support_event(event: dict[str, Any]) -> bool:
    # A lenient draft can store any JSON value as the id, and a list can't be looked up in a set.
    event_id = event.get("id")
    return isinstance(event_id, str) and event_id in SUPPORT_EVENTS


def _find(actions: list[Any], step_type: str) -> dict | None:
    return next((action for action in actions if isinstance(action, dict) and action.get("type") == step_type), None)
