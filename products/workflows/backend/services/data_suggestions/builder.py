import re
from collections import deque
from typing import Any

import structlog

from posthog.dataclasses import frozen

from products.messaging.backend.facade.api import EmailTemplateContent
from products.workflows.backend.facade.contracts import MissingInput
from products.workflows.backend.services.data_suggestions.email_design import EmailCopy, render_email, with_variables
from products.workflows.backend.services.data_suggestions.planner import (
    MAX_PLANNED_STEPS,
    Channel,
    PlannedStep,
    PlannedWorkflow,
    WorkflowIdea,
)

logger = structlog.get_logger(__name__)

# Liquid and Hog tags in model-written copy would render against the recipient's person data.
_TEMPLATE_TAGS = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{[^{}]*\}", re.DOTALL)
_EXIT_ID = "exit_node"
_DEFAULT_MAX_WAIT = "3d"
_REPEAT_ENTRY_SECONDS = 7 * 24 * 60 * 60
# Above this many trigger events a week, a first send would hit the team's email limits and its sender reputation,
# so the draft starts on a random sample that brings the volume down to about this level.
_SAMPLE_ABOVE_WEEKLY_EVENTS = 50_000
_SAMPLE_ID = "action_sample"


@frozen
class EmailSender:
    integration_id: int
    email: str
    name: str


@frozen
class BuildContext:
    allowed_events: frozenset[str]
    step_template_ids: frozenset[str]
    channels: frozenset[Channel]
    email_templates: dict[str, EmailTemplateContent]
    sender: EmailSender | None
    slack_integration_id: int | None
    once_per_person: bool = False
    event_properties: frozenset[str] = frozenset()
    weekly_count: int = 0


@frozen
class BuiltWorkflow:
    uses_saved_template: bool
    workflow: dict[str, Any]


@frozen
class _Link:
    target: str | None
    type: str
    index: int | None = None


def build_workflow(idea: WorkflowIdea, plan: PlannedWorkflow, context: BuildContext) -> BuiltWorkflow | None:
    """Turns a model-written plan into a draft workflow, or None when the plan does not hold up.

    Settings the model cannot know, like credentials, channels and filters, stay blank for the team to fill in.
    The draft cannot be enabled until they do, because enabling validates every step in full.
    """
    if idea.trigger_event not in context.allowed_events:
        _log_rejection("trigger event the project does not send", trigger_event=idea.trigger_event)
        return None
    if not plan.steps or len(plan.steps) > MAX_PLANNED_STEPS:
        _log_rejection("no steps or too many steps", step_count=len(plan.steps))
        return None
    steps = _with_waits_between_emails(plan.steps)
    steps_by_id = {step.id: step for step in steps}
    if len(steps_by_id) != len(steps) or plan.first_step not in steps_by_id:
        _log_rejection("duplicate step ids or unknown first step", first_step=plan.first_step)
        return None
    action_ids = {step.id: f"action_{index}_{step.type}" for index, step in enumerate(steps)}

    links: dict[str, list[_Link]] = {}
    for step in steps:
        step_links = _links(step)
        unknown = [
            link.target for link in step_links or [] if link.target is not None and link.target not in steps_by_id
        ]
        if step_links is None or unknown:
            _log_rejection("step links to an unknown step", step_id=step.id, step_type=step.type, targets=unknown)
            return None
        links[step.id] = step_links
    if not _is_acyclic_and_connected(plan.first_step, links):
        _log_rejection("loop or unreachable step")
        return None

    trigger_config = {
        "type": "event",
        "filters": {"events": [{"id": idea.trigger_event, "name": idea.trigger_event, "type": "events", "order": 0}]},
    }
    actions: list[dict[str, Any]] = [
        {"id": "trigger_node", "name": "Trigger", "description": "", "type": "trigger", "config": trigger_config}
    ]
    edges: list[dict[str, Any]] = [{"from": "trigger_node", "to": action_ids[plan.first_step], "type": "continue"}]
    if context.weekly_count > _SAMPLE_ABOVE_WEEKLY_EVENTS:
        actions.append(_sample_action(context.weekly_count))
        edges = [
            {"from": "trigger_node", "to": _SAMPLE_ID, "type": "continue"},
            {"from": _SAMPLE_ID, "to": action_ids[plan.first_step], "type": "branch", "index": 0},
            {"from": _SAMPLE_ID, "to": _EXIT_ID, "type": "branch", "index": 1},
            {"from": _SAMPLE_ID, "to": _EXIT_ID, "type": "continue"},
        ]
    uses_saved_template = False
    for step in steps:
        action = _build_step(step, action_ids[step.id], context)
        if action is None:
            _log_rejection(
                "step the builder cannot use", step_id=step.id, step_type=step.type, template_id=step.template_id
            )
            return None
        uses_saved_template = uses_saved_template or (step.type == "email" and bool(step.email_template_id))
        actions.append(action)
        for link in links[step.id]:
            edge: dict[str, Any] = {
                "from": action_ids[step.id],
                "to": action_ids[link.target] if link.target else _EXIT_ID,
                "type": link.type,
            }
            if link.index is not None:
                edge["index"] = link.index
            edges.append(edge)
    actions.append(
        {"id": _EXIT_ID, "name": "Exit", "description": "", "type": "exit", "config": {"reason": "Default exit"}}
    )

    return BuiltWorkflow(
        uses_saved_template=uses_saved_template,
        workflow={
            "name": clean_copy(idea.name)[:50],
            "description": clean_copy(idea.description),
            "trigger": trigger_config,
            "actions": actions,
            "edges": edges,
            "conversion": {"filters": [], "window_minutes": None},
            "exit_condition": "exit_only_at_end",
            # A person who repeats the trigger event would otherwise start the sequence again and get every email again.
            "trigger_masking": {
                "hash": "{person.id}",
                "ttl": None if context.once_per_person else _REPEAT_ENTRY_SECONDS,
                "threshold": None,
            },
        },
    )


def _sample_action(weekly_count: int) -> dict[str, Any]:
    share = max(1, _SAMPLE_ABOVE_WEEKLY_EVENTS * 100 // weekly_count)
    return {
        "id": _SAMPLE_ID,
        "name": "Start with a sample",
        "description": f"Sends to {share}% of people first. Raise it once the first emails land well.",
        "type": "random_cohort_branch",
        "config": {
            "cohorts": [
                {"percentage": share, "name": "Gets the workflow"},
                {"percentage": 100 - share, "name": "Skipped for now"},
            ]
        },
    }


def _log_rejection(reason: str, **details: Any) -> None:
    # A rejected plan turns into a 422 for the user, so the reason is only visible here.
    logger.info("workflows.data_suggestions.plan_rejected", reason=reason, **details)


def _links(step: PlannedStep) -> list[_Link] | None:
    """The outgoing edges of a step, in the shape the workflow graph expects."""
    if step.type == "exit":
        return []
    if step.type in ("conditional_branch", "random_split"):
        if not step.branches:
            return None
        branches = [_Link(target=branch.next, type="branch", index=index) for index, branch in enumerate(step.branches)]
        # A split always takes one of its paths, so its continue edge never runs. It points at the exit, and a step
        # reachable only through it fails the reachability check.
        fall_through = step.next if step.type == "conditional_branch" else None
        return [*branches, _Link(target=fall_through, type="continue")]
    if step.type == "wait_until_event":
        return [_Link(target=step.wait_event_next, type="branch", index=0), _Link(target=step.next, type="continue")]
    return [_Link(target=step.next, type="continue")]


def _is_acyclic_and_connected(first_step: str, links: dict[str, list[_Link]]) -> bool:
    # A workflow runs forward only, and a step no path reaches would sit on the canvas doing nothing.
    incoming = dict.fromkeys(links, 0)
    for step_links in links.values():
        for link in step_links:
            if link.target is not None:
                incoming[link.target] += 1
    if incoming[first_step] != 0:
        return False
    queue = deque([first_step])
    visited: set[str] = set()
    while queue:
        step_id = queue.popleft()
        visited.add(step_id)
        for link in links[step_id]:
            if link.target is None:
                continue
            incoming[link.target] -= 1
            if incoming[link.target] == 0:
                queue.append(link.target)
    # Kahn's walk visits every step only when the graph from first_step has no cycle and reaches all steps.
    return visited == set(links)


def _with_waits_between_emails(steps: list[PlannedStep]) -> list[PlannedStep]:
    # Two emails in a row reach the person at the same moment, so a missing wait gets the default one.
    steps_by_id = {step.id: step for step in steps}
    result: list[PlannedStep] = []
    for step in steps:
        following = steps_by_id.get(step.next) if step.next else None
        if step.type == "email" and following is not None and following.type == "email":
            wait_id = f"{step.id}__wait"
            result.append(step.model_copy(update={"next": wait_id}))
            result.append(_wait_step(wait_id, following.id))
        else:
            result.append(step)
    return result


def _wait_step(step_id: str, next_id: str) -> PlannedStep:
    return PlannedStep(
        id=step_id,
        type="delay",
        name="Wait",
        setup_note="",
        next=next_id,
        branches=None,
        template_id=None,
        wait_event=None,
        wait_event_next=None,
        duration="1d",
        email_template_id=None,
        email_subject=None,
        email_heading=None,
        email_paragraphs=None,
        slack_message=None,
    )


def _setup_note(step: PlannedStep) -> str:
    return clean_copy(step.setup_note)[:200] if step.setup_note else ""


def _action(step: PlannedStep, action_id: str, action_type: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": action_id,
        "name": clean_copy(step.name)[:60] or "Step",
        "description": _setup_note(step),
        "type": action_type,
        "config": config,
    }


def _build_step(step: PlannedStep, action_id: str, context: BuildContext) -> dict[str, Any] | None:
    match step.type:
        case "email":
            return _build_email_step(step, action_id, context)
        case "sms" | "push" if step.type not in context.channels:
            return None
        case "sms":
            return _action(step, action_id, "function_sms", {"template_id": "template-twilio", "inputs": {}})
        case "push":
            return _action(step, action_id, "function_push", {"template_id": "template-native-push", "inputs": {}})
        case "slack":
            return _action(step, action_id, "function", _slack_config(step, context))
        case "function":
            if step.template_id not in context.step_template_ids:
                return None
            return _action(step, action_id, "function", {"template_id": step.template_id, "inputs": {}})
        case "delay":
            if not step.duration:
                return None
            return _action(step, action_id, "delay", {"delay_duration": step.duration})
        case "wait_until_time_window":
            # A window of any day and any time is always open, so the step would not wait at all.
            return _action(
                step,
                action_id,
                "wait_until_time_window",
                {"timezone": None, "day": "weekday", "time": ["09:00", "17:00"]},
            )
        case "wait_until_event":
            # A wait with no event never resolves and acts as a plain delay, and enabling does not catch it.
            # An event the project does not send is a made-up name.
            if not step.wait_event or step.wait_event not in context.allowed_events:
                return None
            return _action(step, action_id, "wait_until_condition", _wait_config(step))
        case "conditional_branch":
            # Empty filters, like a branch added in the editor, which rejects null filters. The step's note asks the
            # team to set each condition.
            conditions = [{"filters": {}, "name": clean_copy(branch.label)[:60]} for branch in step.branches or []]
            return _action(step, action_id, "conditional_branch", {"conditions": conditions})
        case "random_split":
            branches = step.branches or []
            # A share outside 1 to 100 still sums to 100 but leaves a path that nobody reaches.
            shares = [branch.percentage or 0 for branch in branches]
            if sum(shares) != 100 or any(not 0 < share <= 100 for share in shares):
                return None
            cohorts = [
                {"percentage": branch.percentage or 0, "name": clean_copy(branch.label)[:60]} for branch in branches
            ]
            return _action(step, action_id, "random_cohort_branch", {"cohorts": cohorts})
        case "exit":
            return _action(step, action_id, "exit", {"reason": clean_copy(step.name)[:100] or "Exit"})


def _slack_config(step: PlannedStep, context: BuildContext) -> dict[str, Any]:
    inputs: dict[str, Any] = {"channel": {"templating": "hog"}}
    if context.slack_integration_id is not None:
        inputs["slack_workspace"] = {"value": context.slack_integration_id, "templating": "hog"}
    if step.slack_message:
        inputs["text"] = {"value": clean_copy(step.slack_message), "templating": "hog"}
    return {"template_id": "template-slack", "inputs": inputs}


def _wait_config(step: PlannedStep) -> dict[str, Any]:
    event = {"id": step.wait_event, "name": step.wait_event, "type": "events", "order": 0}
    return {
        "condition": {"filters": None},
        "events": [{"name": step.wait_event, "filters": {"events": [event]}}],
        "max_wait_duration": step.duration or _DEFAULT_MAX_WAIT,
    }


def _build_email_step(step: PlannedStep, action_id: str, context: BuildContext) -> dict[str, Any] | None:
    if step.email_template_id:
        template = context.email_templates.get(step.email_template_id)
        if template is None:
            return None
        # The email sender rejects a null field, so a field the template does not have stays out.
        body = {
            key: template.email[key]
            for key in ("subject", "html", "text", "design")
            if template.email.get(key) is not None
        }
        name = template.email.get("subject") or "Email"
    else:
        if not (step.email_subject and step.email_heading and step.email_paragraphs):
            return None
        rendered = render_email(
            EmailCopy(
                subject=clean_copy(step.email_subject),
                heading=clean_copy(step.email_heading),
                paragraphs=tuple(clean_copy(paragraph) for paragraph in step.email_paragraphs[:3]),
                variables=context.event_properties,
            )
        )
        body = {"subject": rendered.subject, "html": rendered.html, "text": rendered.text, "design": rendered.design}
        # The step name is cut to fit the canvas, so it takes the fallback words rather than a Liquid tag.
        name = with_variables(clean_copy(step.email_subject), frozenset())

    sender = context.sender
    return {
        "id": action_id,
        "name": name[:60],
        "description": _setup_note(step),
        "type": "function_email",
        "config": {
            "template_id": "template-email",
            "inputs": {
                "email": {
                    "templating": "liquid",
                    "value": {
                        "to": {"email": "{{ person.properties.email }}", "name": ""},
                        "from": (
                            {"integrationId": sender.integration_id, "email": sender.email, "name": sender.name}
                            if sender
                            else {"email": "", "name": ""}
                        ),
                        "replyTo": "",
                        "preheader": "",
                        **body,
                    },
                }
            },
        },
    }


def clean_copy(text: str) -> str:
    cleaned = re.sub(r"\s*—\s*", ", ", _TEMPLATE_TAGS.sub("", text))
    # Removing one tag can join the braces around it into a new one, so no brace may remain at all.
    cleaned = cleaned.replace("{", "").replace("}", "").strip()
    # Sentence case starts with a capital, which the model does not always write.
    return cleaned[:1].upper() + cleaned[1:]


def missing_inputs(
    workflow: dict[str, Any], input_schemas: dict[str, list[dict[str, Any]]], *, sender_field: str = "Email sender"
) -> tuple[MissingInput, ...]:
    """The settings a draft leaves blank: required template inputs, the email sender and unset branch conditions.
    `input_schemas` maps a template id to its inputs schema."""
    missing: list[MissingInput] = []
    for action in workflow["actions"]:
        config = action.get("config") or {}
        fields: list[str] = []
        if action["type"] == "conditional_branch":
            fields += [
                f"Condition: {condition.get('name') or 'unnamed'}"
                for condition in config.get("conditions") or []
                if not _has_conditions(condition.get("filters"))
            ]
        if action["type"] == "function_email":
            sender = (((config.get("inputs") or {}).get("email") or {}).get("value") or {}).get("from") or {}
            if not sender.get("email"):
                fields.append(sender_field)
        else:
            inputs = config.get("inputs") or {}
            fields += [
                item.get("label") or item.get("key") or "input"
                for item in input_schemas.get(config.get("template_id") or "", [])
                if item.get("required") and _is_blank((inputs.get(item.get("key")) or {}).get("value"))
            ]
        step_name = action.get("name") or action["id"]
        missing += [MissingInput(step_id=action["id"], step_name=step_name, field=field) for field in fields]
    return tuple(missing)


def _has_conditions(filters: Any) -> bool:
    # The draft check compiles every condition, so an unset one still carries source and bytecode keys.
    return isinstance(filters, dict) and any(filters.get(key) for key in ("properties", "events", "actions"))


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}
