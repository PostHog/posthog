import re
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from posthog.dataclasses import frozen

from products.workflows.backend.services.workflow_code.document import (
    BranchStep,
    Condition,
    DelayStep,
    EmailStep,
    EventTrigger,
    FunctionStep,
    PassThroughStep,
    PassThroughTrigger,
    ScheduleTrigger,
    WebhookStep,
    WorkflowDocument,
)
from products.workflows.backend.services.workflow_code.errors import (
    DocumentError,
    DocumentInvalid,
    DocumentPath,
    WorkflowCodeErrorStatus,
    describe_path,
)

TRIGGER_NODE_ID = "trigger_node"
EXIT_NODE_ID = "exit_node"
EMAIL_TEMPLATE_ID = "template-email"
WEBHOOK_TEMPLATE_ID = "template-webhook"
MAX_STEP_ID_LENGTH = 200
# Set by the workflow editor on each step it creates. They are bookkeeping, not content, so a file keeps them.
EDITOR_ACTION_FIELDS = ("created_at", "updated_at")

_SLUG_SEPARATORS = re.compile(r"[^a-z0-9]+")

DocumentStep = DelayStep | BranchStep | EmailStep | WebhookStep | FunctionStep | PassThroughStep


class FunctionTemplate(Protocol):
    inputs_schema: Any


@frozen
class CompiledWorkflow:
    definition: dict[str, Any]
    step_paths: dict[str, DocumentPath]
    input_paths: dict[str, DocumentPath]
    template_paths: dict[str, DocumentPath]


def slug(name: str) -> str:
    return _SLUG_SEPARATORS.sub("_", name.lower()).strip("_")


def compile_document(document: WorkflowDocument) -> CompiledWorkflow:
    """Turn a validated document into the definition fields HogFlowSerializer accepts."""
    compiler = _Compiler()
    trigger = compiler.trigger_action(document.trigger)
    compiler.claim_ids(document.steps, ("steps",))
    entry = compiler.path(document.steps, ("steps",), EXIT_NODE_ID)
    if compiler.errors:
        raise DocumentInvalid(compiler.errors)
    return CompiledWorkflow(
        definition={
            "name": document.name,
            "description": document.description,
            "status": document.status,
            "exit_condition": document.exit_condition,
            "variables": [variable.model_dump() for variable in document.variables],
            "actions": [
                trigger,
                *compiler.actions,
                {
                    "id": EXIT_NODE_ID,
                    "name": "Exit",
                    "description": document.exit.description,
                    "type": "exit",
                    "config": {"reason": document.exit.reason},
                },
            ],
            "edges": [{"from": TRIGGER_NODE_ID, "to": entry, "type": "continue"}, *compiler.edges],
        },
        step_paths={TRIGGER_NODE_ID: ("trigger",), EXIT_NODE_ID: ("exit",), **compiler.step_paths},
        input_paths=compiler.input_paths,
        template_paths=compiler.template_paths,
    )


def with_stored_editor_fields(definition: dict[str, Any], stored_actions: list[dict[str, Any]]) -> dict[str, Any]:
    """The definition with each step's editor timestamps taken from the stored step with the same id."""
    stored_by_id = {action.get("id"): action for action in stored_actions if isinstance(action, dict)}
    actions = []
    for action in definition["actions"]:
        stored = stored_by_id.get(action["id"], {})
        actions.append({**action, **{field: stored[field] for field in EDITOR_ACTION_FIELDS if field in stored}})
    return {**definition, "actions": actions}


def template_errors(
    compiled: CompiledWorkflow, get_template: Callable[[str], FunctionTemplate | None]
) -> list[DocumentError]:
    """Refuse function steps whose template does not exist, and any value for a secret input."""
    errors: list[DocumentError] = []
    for action in compiled.definition["actions"]:
        config = action.get("config") or {}
        template_id = config.get("template_id")
        if not isinstance(template_id, str):
            continue
        template = get_template(template_id)
        if template is None:
            if action["id"] in compiled.template_paths:
                errors.append(_unknown_template(template_id, compiled.template_paths[action["id"]]))
            continue
        inputs_path = compiled.input_paths.get(action["id"])
        inputs = config.get("inputs")
        if inputs_path is None or not isinstance(inputs, dict):
            continue
        secret_keys = {item["key"] for item in (template.inputs_schema or []) if item.get("secret")}
        errors.extend(_secret_input(action, key, (*inputs_path, key)) for key in inputs if key in secret_keys)
    return errors


def definition_errors(detail: Any, compiled: CompiledWorkflow) -> list[DocumentError]:
    """Place the errors HogFlowSerializer and validate_graph raise on the compiled definition back in the file."""
    if not isinstance(detail, dict):
        return [_invalid_workflow(message, None) for message in _messages(detail)]
    errors: list[DocumentError] = []
    for field, value in detail.items():
        if field == "actions" and isinstance(value, dict):
            for index, action_detail in value.items():
                action_id = compiled.definition["actions"][int(index)]["id"]
                errors.append(_invalid_workflow(" ".join(_messages(action_detail)), compiled.step_paths.get(action_id)))
        elif field == "graph":
            errors.extend(_invalid_workflow(message, _step_named_in(message, compiled)) for message in _messages(value))
        else:
            path: DocumentPath | None = (field,) if field in _DOCUMENT_FIELDS else None
            errors.append(_invalid_workflow(" ".join(_messages(value)), path))
    return errors


_DOCUMENT_FIELDS = {"name", "description", "status", "exit_condition", "variables"}
_QUOTED = re.compile(r"'([^']+)'")


def _messages(detail: Any) -> list[str]:
    if isinstance(detail, dict):
        return [message for value in detail.values() for message in _messages(value)]
    if isinstance(detail, list):
        return [message for value in detail for message in _messages(value)]
    return [str(detail)]


def _step_named_in(message: str, compiled: CompiledWorkflow) -> DocumentPath | None:
    for action_id in _QUOTED.findall(message):
        if action_id in compiled.step_paths:
            return compiled.step_paths[action_id]
    return None


def _invalid_workflow(message: str, path: DocumentPath | None) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.INVALID_WORKFLOW,
        message=f"{describe_path(path)}: {message}",
        why="PostHog checks the workflow the file compiles to the same way it checks every workflow it saves, and this part does not pass.",
        fix="Change this part of the file as the message says, then check the file again.",
        path=path,
    )


def _unknown_template(template_id: str, path: DocumentPath) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.UNKNOWN_TEMPLATE,
        message=f"{describe_path(path)} is {template_id}, which is not a function template PostHog has.",
        why="A function step runs a template, and PostHog looks the template up by its id.",
        fix="Use the id of an existing template, for example template-slack. The function templates API lists them.",
        path=path,
    )


def _secret_input(action: dict[str, Any], key: str, path: DocumentPath) -> DocumentError:
    return DocumentError(
        status=WorkflowCodeErrorStatus.SECRET_INPUT,
        message=f"{describe_path(path)} sets a value for {key}, which is a secret input of {action['name']}.",
        why="A workflow file is committed to a repository, so it cannot carry secrets. When the file leaves the input out, PostHog keeps the value already stored on the workflow.",
        fix=f"Remove {key} from the file.",
        path=path,
    )


class _Compiler:
    def __init__(self) -> None:
        self.actions: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.errors: list[DocumentError] = []
        self.step_paths: dict[str, DocumentPath] = {}
        self.input_paths: dict[str, DocumentPath] = {}
        self.template_paths: dict[str, DocumentPath] = {}
        self._id_owners: dict[str, DocumentPath] = {TRIGGER_NODE_ID: ("trigger",), EXIT_NODE_ID: ("exit",)}
        self._ids: dict[DocumentPath, str] = {}

    def trigger_action(self, trigger: EventTrigger | ScheduleTrigger | PassThroughTrigger) -> dict[str, Any]:
        if isinstance(trigger, EventTrigger):
            config: dict[str, Any] = {
                "type": "event",
                "filters": {
                    "events": [
                        {
                            "id": trigger.event,
                            "name": trigger.event,
                            "type": "events",
                            "order": 0,
                            "properties": [_property_filter(condition) for condition in trigger.properties],
                        }
                    ],
                    "properties": [],
                    "filter_test_accounts": trigger.filter_test_accounts,
                },
            }
        elif isinstance(trigger, ScheduleTrigger):
            config = {"type": "schedule"}
        else:
            config = {**trigger.config, "type": trigger.type}
            self.input_paths[TRIGGER_NODE_ID] = ("trigger", "config", "inputs")
        return {
            "id": TRIGGER_NODE_ID,
            "name": trigger.name,
            "description": trigger.description,
            "type": "trigger",
            "config": config,
        }

    def claim_ids(self, steps: Sequence[DocumentStep], path: DocumentPath) -> None:
        """Give every step its id in file order, so a clash is reported on the later of the two steps."""
        for index, step in enumerate(steps):
            step_path: DocumentPath = (*path, index)
            self._ids[step_path] = self._claim_id(step, step_path)
            for branch_steps, branch_path in self._branches(step, step_path):
                self.claim_ids(branch_steps, branch_path)

    def path(self, steps: Sequence[DocumentStep], path: DocumentPath, continuation: str) -> str:
        """Emit the steps of one list and return the id a run enters it by."""
        ids = [self._ids[(*path, index)] for index in range(len(steps))]
        for index, (step, action_id) in enumerate(zip(steps, ids)):
            step_path: DocumentPath = (*path, index)
            following = ids[index + 1] if index + 1 < len(ids) else continuation
            self.step_paths[action_id] = step_path
            self.actions.append(
                {
                    "id": action_id,
                    "name": step.name,
                    "description": step.description,
                    **self._action_body(step, action_id, step_path),
                }
            )
            self.edges.append({"from": action_id, "to": following, "type": "continue"})
            for branch_index, (branch_steps, branch_path) in enumerate(self._branches(step, step_path)):
                entry = self.path(branch_steps, branch_path, following)
                self.edges.append({"from": action_id, "to": entry, "type": "branch", "index": branch_index})
        return ids[0] if ids else continuation

    def _claim_id(self, step: DocumentStep, step_path: DocumentPath) -> str:
        field = "id" if step.id is not None else "name"
        action_id = step.id if step.id is not None else slug(step.name)
        field_path: DocumentPath = (*step_path, field)
        if not action_id:
            self.errors.append(
                DocumentError(
                    status=WorkflowCodeErrorStatus.INVALID_VALUE,
                    message=f"{describe_path(field_path)} has no letters or digits, so it gives the step no id.",
                    why="A step's id is its name in lower case with other characters turned into _, and PostHog tracks the people in each step by that id.",
                    fix="Add letters or digits to the name, or give the step an explicit id.",
                    path=field_path,
                )
            )
            return ""
        if len(action_id) > MAX_STEP_ID_LENGTH:
            self.errors.append(
                DocumentError(
                    status=WorkflowCodeErrorStatus.INVALID_VALUE,
                    message=f"{describe_path(field_path)} gives the step an id of {len(action_id)} characters.",
                    why=f"A step id is at most {MAX_STEP_ID_LENGTH} characters, because PostHog copies it into every edge to the step.",
                    fix="Give the step a shorter explicit id.",
                    path=field_path,
                )
            )
            return action_id
        owner = self._id_owners.get(action_id)
        if owner is not None:
            self.errors.append(
                DocumentError(
                    status=WorkflowCodeErrorStatus.DUPLICATE_STEP_ID,
                    message=f"{describe_path(field_path)} gives the step the id {action_id}, which {describe_path(owner)} already has.",
                    why="PostHog tracks the people in each step by its id, so two steps cannot share one.",
                    fix="Give one of the two steps an explicit id, or a different name.",
                    path=field_path,
                )
            )
            return action_id
        self._id_owners[action_id] = step_path
        return action_id

    def _action_body(self, step: DocumentStep, action_id: str, step_path: DocumentPath) -> dict[str, Any]:
        match step:
            case DelayStep():
                return {"type": "delay", "config": {"delay_duration": step.duration}}
            case BranchStep():
                return {
                    "type": "conditional_branch",
                    "config": {
                        "conditions": [
                            {
                                "name": arm.name,
                                "filters": {"properties": [_property_filter(condition) for condition in arm.when]},
                            }
                            for arm in step.arms
                        ]
                    },
                }
            case EmailStep():
                return {"type": "function_email", "config": _email_config(step)}
            case WebhookStep():
                return {"type": "function", "config": _webhook_config(step)}
            case FunctionStep():
                self.input_paths[action_id] = (*step_path, "inputs")
                self.template_paths[action_id] = (*step_path, "template")
                return {
                    "type": "function",
                    "config": {
                        "template_id": step.template,
                        "inputs": {key: {"value": value} for key, value in step.inputs.items()},
                    },
                }
            case PassThroughStep():
                self.input_paths[action_id] = (*step_path, "config", "inputs")
                return {"type": step.action_type, "config": dict(step.config)}

    def _branches(
        self, step: DocumentStep, step_path: DocumentPath
    ) -> list[tuple[Sequence[DocumentStep], DocumentPath]]:
        if isinstance(step, BranchStep):
            return [(arm.then, (*step_path, "arms", index, "then")) for index, arm in enumerate(step.arms)]
        if isinstance(step, PassThroughStep):
            return [(steps, (*step_path, "branches", index)) for index, steps in enumerate(step.branches)]
        return []


def _property_filter(condition: Condition) -> dict[str, Any]:
    kind, key = ("person", condition.person) if condition.person is not None else ("event", condition.event)
    property_filter: dict[str, Any] = {"key": key, "type": kind, "operator": condition.operator}
    if condition.value is not None:
        property_filter["value"] = condition.value
    return property_filter


def _email_config(step: EmailStep) -> dict[str, Any]:
    sender: dict[str, Any] = {"integrationIds": step.sender.integration_ids}
    if step.sender.name is not None:
        sender["name"] = step.sender.name
    if step.sender.email is not None:
        sender["email"] = step.sender.email
    email: dict[str, Any] = {
        "from": sender,
        "to": {"email": step.to.email, "name": step.to.name},
        "subject": step.subject,
    }
    for field in ("text", "html", "preheader"):
        if getattr(step, field) is not None:
            email[field] = getattr(step, field)
    return {"template_id": EMAIL_TEMPLATE_ID, "inputs": {"email": {"value": email, "templating": "liquid"}}}


def _webhook_config(step: WebhookStep) -> dict[str, Any]:
    inputs: dict[str, Any] = {"url": {"value": step.url}, "method": {"value": step.method}}
    if step.headers is not None:
        inputs["headers"] = {"value": step.headers}
    if step.body is not None:
        inputs["body"] = {"value": step.body}
    return {"template_id": WEBHOOK_TEMPLATE_ID, "inputs": inputs}
