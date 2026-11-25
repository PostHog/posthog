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
# Support replies and ticket updates must reach people who opted out of marketing email.
SUPPORT_EVENT_PREFIX: Final[str] = "$conversation_"
SUPPORT_TRIGGER_TYPES: Final[frozenset[str]] = frozenset({"event", "internal-event"})


def is_transactional_origin(origin_product: str | None) -> bool:
    return origin_product in TRANSACTIONAL_STEPS


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


def reserved_step_ids(actions: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {action["id"] for action in actions if isinstance(action, dict) and action.get("id") in RESERVED_STEP_IDS}
    )


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
    filters = config.get("filters") or {}
    events = filters.get("events") or []
    # The filter compiler matches the event name only on entries of type `events`, so another entry matches any event.
    return (
        config.get("type") in SUPPORT_TRIGGER_TYPES
        and bool(events)
        and not filters.get("actions")
        and all(
            isinstance(event, dict)
            and event.get("type") == "events"
            and str(event.get("id") or "").startswith(SUPPORT_EVENT_PREFIX)
            for event in events
        )
    )


def _find(actions: list[Any], step_type: str) -> dict | None:
    return next((action for action in actions if isinstance(action, dict) and action.get("type") == step_type), None)
