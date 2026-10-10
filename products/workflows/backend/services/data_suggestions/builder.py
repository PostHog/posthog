import re
from collections import deque
from typing import Any

from posthog.dataclasses import frozen

from products.workflows.backend.services.data_suggestions.email_design import EmailCopy, render_email
from products.workflows.backend.services.data_suggestions.planner import (
    MAX_PLANNED_STEPS,
    Channel,
    PlannedStep,
    PlannedWorkflow,
    WorkflowIdea,
)

# Liquid and Hog tags in model-written copy would render against the recipient's person data.
_TEMPLATE_TAGS = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
_EXIT_ID = "exit_node"
_DEFAULT_MAX_WAIT = "3d"


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
    email_templates: dict[str, dict]
    sender: EmailSender | None
    slack_integration_id: int | None


@frozen
class BuiltWorkflow:
    name: str
    description: str
    reason: str
    trigger_event: str
    step_types: tuple[str, ...]
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
    if idea.trigger_event not in context.allowed_events or not plan.steps or len(plan.steps) > MAX_PLANNED_STEPS:
        return None
    steps = _with_waits_between_emails(plan.steps)
    steps_by_id = {step.id: step for step in steps}
    if len(steps_by_id) != len(steps) or plan.first_step not in steps_by_id:
        return None
    action_ids = {step.id: f"action_{index}_{step.type}" for index, step in enumerate(steps)}

    links: dict[str, list[_Link]] = {}
    for step in steps:
        step_links = _links(step)
        if step_links is None or any(link.target is not None and link.target not in steps_by_id for link in step_links):
            return None
        links[step.id] = step_links
    if not _is_acyclic_and_connected(plan.first_step, links):
        return None

    trigger_config = {
        "type": "event",
        "filters": {"events": [{"id": idea.trigger_event, "name": idea.trigger_event, "type": "events", "order": 0}]},
    }
    actions: list[dict[str, Any]] = [
        {"id": "trigger_node", "name": "Trigger", "description": "", "type": "trigger", "config": trigger_config}
    ]
    edges: list[dict[str, Any]] = [{"from": "trigger_node", "to": action_ids[plan.first_step], "type": "continue"}]
    uses_saved_template = False
    for step in steps:
        action = _build_step(step, action_ids[step.id], context)
        if action is None:
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

    name = clean_copy(idea.name)[:50]
    return BuiltWorkflow(
        name=name,
        description=clean_copy(idea.description),
        reason=clean_copy(idea.reason),
        trigger_event=idea.trigger_event,
        step_types=tuple(step.type for step in steps),
        uses_saved_template=uses_saved_template,
        workflow={
            "name": name,
            "description": clean_copy(idea.description),
            "trigger": trigger_config,
            "actions": actions,
            "edges": edges,
            "conversion": {"filters": [], "window_minutes": None},
            "exit_condition": "exit_only_at_end",
        },
    )


def _links(step: PlannedStep) -> list[_Link] | None:
    """The outgoing edges of a step, in the shape the workflow graph expects."""
    if step.type == "exit":
        return []
    if step.type in ("conditional_branch", "random_split"):
        if not step.branches:
            return None
        branches = [_Link(target=branch.next, type="branch", index=index) for index, branch in enumerate(step.branches)]
        return [*branches, _Link(target=step.next, type="continue")]
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
            return _action(step, action_id, "wait_until_time_window", {"timezone": None, "day": "any", "time": "any"})
        case "wait_until_event":
            return _action(step, action_id, "wait_until_condition", _wait_config(step, context))
        case "conditional_branch":
            conditions = [{"filters": {}, "name": clean_copy(branch.label)[:60]} for branch in step.branches or []]
            return _action(step, action_id, "conditional_branch", {"conditions": conditions})
        case "random_split":
            branches = step.branches or []
            if sum(branch.percentage or 0 for branch in branches) != 100:
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


def _wait_config(step: PlannedStep, context: BuildContext) -> dict[str, Any]:
    # An event the project does not send is a made-up name, so the wait is left for the team to set.
    events = (
        [
            {
                "name": step.wait_event,
                "filters": {"events": [{"id": step.wait_event, "name": step.wait_event, "type": "events", "order": 0}]},
            }
        ]
        if step.wait_event and step.wait_event in context.allowed_events
        else []
    )
    return {
        "condition": {"filters": None},
        "events": events,
        "max_wait_duration": step.duration or _DEFAULT_MAX_WAIT,
    }


def _build_email_step(step: PlannedStep, action_id: str, context: BuildContext) -> dict[str, Any] | None:
    if step.email_template_id:
        content = context.email_templates.get(step.email_template_id)
        if content is None:
            return None
        body = {key: content.get(key) for key in ("subject", "html", "text", "design")}
        name = content.get("subject") or "Email"
    else:
        if not (step.email_subject and step.email_heading and step.email_paragraphs):
            return None
        rendered = render_email(
            EmailCopy(
                subject=clean_copy(step.email_subject),
                heading=clean_copy(step.email_heading),
                paragraphs=tuple(clean_copy(paragraph) for paragraph in step.email_paragraphs[:3]),
            )
        )
        body = {"subject": rendered.subject, "html": rendered.html, "text": rendered.text, "design": rendered.design}
        name = rendered.subject

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
    cleaned = _TEMPLATE_TAGS.sub("", text).replace("—", ", ").strip()
    # Sentence case starts with a capital, which the model does not always write.
    return cleaned[:1].upper() + cleaned[1:]
