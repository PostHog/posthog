"""A text outline of a workflow's steps, in the order a contact runs through them."""

from collections import defaultdict
from typing import Any

from posthog.dataclasses import frozen

# Slack collapses leading spaces, but keeps an em space.
INDENT = " "
TRIGGER_DESCRIPTIONS = {
    "manual": "run manually",
    "webhook": "webhook",
    "tracking_pixel": "tracking pixel",
    "schedule": "on a schedule",
    "batch": "batch run",
    "data-warehouse-table": "new rows in a data warehouse table",
    "data-warehouse-view": "new rows in a data warehouse view",
    "internal-event": "PostHog event",
}


@frozen
class EmailStep:
    action_id: str
    title: str


@frozen
class WorkflowOutline:
    lines: tuple[str, ...]
    email_steps: tuple[EmailStep, ...]


def outline_workflow(actions: Any, edges: Any) -> WorkflowOutline:
    return _OutlineWalk(_dicts(actions), _dicts(edges)).run()


def _dicts(items: Any) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


class _OutlineWalk:
    def __init__(self, actions: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        self.actions = actions
        self.actions_by_id = {action.get("id"): action for action in actions}
        self.edges_from: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            self.edges_from[edge.get("from")].append(edge)
        self.visited: set[Any] = set()
        self.lines: list[str] = []
        self.email_steps: list[EmailStep] = []

    def run(self) -> WorkflowOutline:
        trigger = next((action for action in self.actions if action.get("type") == "trigger"), None)
        if trigger:
            self._walk_path(trigger.get("id"), depth=0)
        return WorkflowOutline(lines=tuple(self.lines), email_steps=tuple(self.email_steps))

    def _walk_path(self, action_id: Any, depth: int) -> None:
        indent = INDENT * depth
        while action_id is not None:
            action = self.actions_by_id.get(action_id)
            if action is None or action.get("type") == "exit":
                return
            if action_id in self.visited:
                self.lines.append(
                    f'{indent}• Continues at "{_name(action)}"'
                    if _name(action)
                    else f"{indent}• Continues at an earlier step"
                )
                return
            self.visited.add(action_id)
            self.lines.append(f"{indent}• {_describe_action(action)}")
            if action.get("type") == "function_email":
                self.email_steps.append(
                    EmailStep(action_id=str(action_id), title=_email_subject(action) or _name(action))
                )

            outgoing = self.edges_from[action_id]
            next_step = next((edge.get("to") for edge in outgoing if edge.get("type") == "continue"), None)
            branches = sorted(
                (edge for edge in outgoing if edge.get("type") == "branch"), key=lambda edge: edge.get("index") or 0
            )
            if not branches:
                action_id = next_step
                continue
            for branch in branches:
                self.lines.append(f"{indent}{INDENT}↳ {_describe_branch(action, branch.get('index') or 0)}")
                self._walk_path(branch.get("to"), depth + 2)
            if next_step is not None and self.actions_by_id.get(next_step, {}).get("type") != "exit":
                self.lines.append(f"{indent}{INDENT}↳ {_describe_fallback(action)}")
                self._walk_path(next_step, depth + 2)
            return


def _name(action: dict[str, Any]) -> str:
    return str(action.get("name") or "")


def _config(action: dict[str, Any]) -> dict[str, Any]:
    config = action.get("config")
    return config if isinstance(config, dict) else {}


def _email_subject(action: dict[str, Any]) -> str:
    email = (_config(action).get("inputs") or {}).get("email") or {}
    template = email.get("value") if isinstance(email, dict) else None
    return str(template.get("subject") or "") if isinstance(template, dict) else ""


def _label(name: str, detail: str) -> str:
    return ": ".join(part for part in (name, detail) if part)


def _describe_action(action: dict[str, Any]) -> str:
    config = _config(action)
    subject = _email_subject(action)
    max_wait = config.get("max_wait_duration")
    match action.get("type"):
        case "trigger":
            return f"Trigger: {_describe_trigger(config)}"
        case "function_email":
            return _label(_name(action), f'email "{subject}"' if subject else "email")
        case "function_sms":
            return _label(_name(action), "SMS")
        case "function_push":
            return _label(_name(action), "push notification")
        case "delay":
            return _label(_name(action), str(config.get("delay_duration") or "until a date"))
        case "wait_until_condition":
            return _label(_name(action), f"up to {max_wait}" if max_wait else "")
        case _:
            return _name(action)


def _describe_trigger(config: dict[str, Any]) -> str:
    trigger_type = str(config.get("type") or "")
    if trigger_type != "event":
        return TRIGGER_DESCRIPTIONS.get(trigger_type, trigger_type)
    filters = config.get("filters")
    entities = [*(filters.get("events") or []), *(filters.get("actions") or [])] if isinstance(filters, dict) else []
    names = [
        str(entity.get("name") or entity.get("id") or "")
        for entity in entities
        if isinstance(entity, dict) and (entity.get("name") or entity.get("id") is not None)
    ]
    return ", ".join(names) if names else "any event"


def _describe_branch(action: dict[str, Any], index: int) -> str:
    config = _config(action)
    match action.get("type"):
        case "wait_until_condition":
            return _describe_wait_match(config)
        case "random_cohort_branch":
            cohort = _at(config.get("cohorts"), index)
            label = str(cohort.get("name") or f"If cohort #{index + 1} matches")
            percentage = cohort.get("percentage")
            return label if percentage is None else f"{label} ({percentage}%)"
        case "conditional_branch":
            return str(_at(config.get("conditions"), index).get("name") or f"If condition #{index + 1} matches")
        case _:
            return f"If condition #{index + 1} matches"


def _describe_fallback(action: dict[str, Any]) -> str:
    match action.get("type"):
        case "wait_until_condition":
            max_wait = _config(action).get("max_wait_duration")
            return f"No match within {max_wait}" if max_wait else "No match"
        case "random_cohort_branch":
            return "Fallback if no cohort has traffic"
        case _:
            return "No match"


def _describe_wait_match(config: dict[str, Any]) -> str:
    condition = config.get("condition")
    if not isinstance(condition, dict):
        condition = {}
    if condition.get("name"):
        return str(condition["name"])
    waits_for_event = any(_targets_an_event(entry.get("filters")) for entry in _dicts(config.get("events")))
    if not waits_for_event:
        return "Condition matched"
    condition_filters = condition.get("filters")
    has_condition = _targets_an_event(condition_filters) or (
        isinstance(condition_filters, dict) and bool(condition_filters.get("properties"))
    )
    return "Condition or event matched" if has_condition else "Event received"


def _targets_an_event(filters: Any) -> bool:
    return isinstance(filters, dict) and bool(filters.get("events") or filters.get("actions"))


def _at(items: Any, index: int) -> dict[str, Any]:
    item = items[index] if isinstance(items, list) and 0 <= index < len(items) else None
    return item if isinstance(item, dict) else {}
