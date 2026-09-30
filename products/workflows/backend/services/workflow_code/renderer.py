import re
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, TypeAdapter, ValidationError

from posthog.cdp.validation import build_html_wrap_design
from posthog.dataclasses import frozen

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.workflow_code.compiler import (
    EMAIL_TEMPLATE_ID,
    EXIT_NODE_ID,
    TRIGGER_NODE_ID,
    WEBHOOK_TEMPLATE_ID,
    DocumentStep,
    DocumentTrigger,
    slug,
    step_action_body,
    trigger_config,
)
from products.workflows.backend.services.workflow_code.document import (
    PASS_THROUGH_TRIGGER_TYPES,
    STEP_ID_PATTERN,
    EmailRecipient,
    Step,
    Trigger,
    Variable,
    WorkflowDocument,
    key_from_name,
)
from products.workflows.backend.services.workflow_code.yaml_dumper import dump_workflow_file
from products.workflows.backend.services.workflow_code.yaml_loader import MAX_CONTENT_BYTES, MAX_DEPTH, MAX_VALUES

_DERIVED_KEYS = frozenset({"bytecode", "bytecode_error", "bytecode_contract", "transpiled"})
_INPUT_DERIVED_KEYS = _DERIVED_KEYS | {"order"}
# Filter validation adds the default source to every filter it checks.
_DEFAULT_FILTER_SOURCE = "events"
_BRANCH_COUNT_KEYS = {"conditional_branch": "conditions", "random_cohort_branch": "cohorts"}
_NOT_IN_THE_FILE = ("conversion", "trigger_masking", "email_sending_rate_limit", "abort_action")
_LEADING_FIELDS = ("version", "key", "type", "id", "name")
_TRAILING_FIELDS = ("output_variable",)
_EDITOR_FIELDS = ("created_at", "updated_at")
_NODE_FIELDS = frozenset({"id", "name", "description", "type", "config", *_EDITOR_FIELDS})
_STEP_FIELDS = _NODE_FIELDS | {"output_variable"}
# Header, input and query names that usually hold a credential the template does not mark as secret.
_CREDENTIAL_NAME = re.compile(
    r"^(?:proxy-)?authorization$|cookie|token|secret|passw|api[-_]?key|access[-_]?key|^x-auth", re.IGNORECASE
)
_MAX_STEP_ID_LENGTH = 200
_SHRINK_IT = "An email design from the email editor is the usual cause. Make the workflow smaller in PostHog before you pull it again."
_DOCUMENT_STATUSES = (HogFlow.State.DRAFT, HogFlow.State.ACTIVE)
# Each nested branch adds about four levels to the file, and the loader refuses files deeper than 100.
MAX_BRANCH_DEPTH = 15

_step_adapter: TypeAdapter[DocumentStep] = TypeAdapter(Step)
_trigger_adapter: TypeAdapter[DocumentTrigger] = TypeAdapter(Trigger)


@frozen
class RenderWarning:
    action_id: str | None
    message: str


@frozen
class RenderedWorkflow:
    content: str
    warnings: tuple[RenderWarning, ...]


def render_workflow(definition: dict[str, Any], *, key: str | None) -> RenderedWorkflow:
    """The workflow as a file that compiles back to it, with a warning for each part the file cannot carry.

    `definition` is the workflow as the workflows API returns it, with secret inputs masked.
    """
    return _Renderer(definition).render(key)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _is_set(value: Any) -> bool:
    if isinstance(value, dict | list | str):
        return bool(value)
    return value is not None


def _is_secret_marker(value: Any) -> bool:
    return isinstance(value, dict) and value.get("secret") is True and "value" not in value


def _file_config(value: Any) -> Any:
    """A stored config as a file carries it.

    Validation adds bytecode and an input order, fills in the default filter source and wraps an html-only
    email in a design, and a read masks secret inputs. The file leaves those out. It never looks inside an
    input's value, which is the user's own data.
    """
    if isinstance(value, list):
        return [_file_config(item) for item in value]
    if not isinstance(value, dict):
        return value
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key == "inputs" and isinstance(item, dict):
            cleaned[key] = _file_inputs(item)
        elif key == "filters" and isinstance(item, dict):
            cleaned[key] = {
                filter_key: _file_config(filter_value)
                for filter_key, filter_value in item.items()
                if filter_key not in _DERIVED_KEYS
            }
        else:
            cleaned[key] = _file_config(item)
    return cleaned


def _without_default_source(filters: Any) -> Any:
    if not isinstance(filters, dict):
        return filters
    return {key: value for key, value in filters.items() if not (key == "source" and value == _DEFAULT_FILTER_SOURCE)}


def _without_filled_in_sources(action_type: Any, config: dict[str, Any]) -> dict[str, Any]:
    """The config without the default filter source in the filters that validation fills it back into."""
    cleaned = dict(config)
    if action_type == "trigger":
        if cleaned.get("type") == "event" and "filters" in cleaned:
            cleaned["filters"] = _without_default_source(cleaned["filters"])
        return cleaned
    if isinstance(cleaned.get("conditions"), list):
        cleaned["conditions"] = [_with_filters_cleaned(condition) for condition in cleaned["conditions"]]
    if isinstance(cleaned.get("condition"), dict):
        cleaned["condition"] = _with_filters_cleaned(cleaned["condition"])
    if action_type == "wait_until_condition" and isinstance(cleaned.get("events"), list):
        cleaned["events"] = [_with_filters_cleaned(event) for event in cleaned["events"]]
    return cleaned


def _with_filters_cleaned(entry: Any) -> Any:
    if not isinstance(entry, dict) or "filters" not in entry:
        return entry
    return {**entry, "filters": _without_default_source(entry["filters"])}


def _credential_names(inputs: dict[str, Any]) -> list[str]:
    """Where the inputs hold something named like a credential: an input, a header or a URL query key."""
    found: list[str] = []
    for key, raw in inputs.items():
        value = raw.get("value") if isinstance(raw, dict) else raw
        if _is_secret_marker(raw) or not _is_set(value):
            continue
        if _CREDENTIAL_NAME.search(key):
            found.append(f"the input {key}")
        if isinstance(value, dict):
            found += [
                f"{name} in the input {key}"
                for name, item in value.items()
                if isinstance(name, str) and _CREDENTIAL_NAME.search(name) and _is_set(item)
            ]
        elif isinstance(value, str) and "?" in value:
            found += [
                f"{name} in the query of the input {key}"
                for name, _item in parse_qsl(urlsplit(value).query)
                if _CREDENTIAL_NAME.search(name)
            ]
    return found


@frozen
class _Shape:
    depth: int
    values: int


def _shape(value: Any) -> _Shape:
    """How deep the data nests, and how many values it holds as the loader counts them, keys included."""
    deepest, values = 0, 0
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        deepest = max(deepest, depth)
        values += 1
        if isinstance(item, dict):
            values += len(item)
            pending += [(child, depth + 1) for child in item.values()]
        elif isinstance(item, list):
            pending += [(child, depth + 1) for child in item]
    return _Shape(depth=deepest, values=values)


def _file_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, raw in inputs.items():
        if _is_secret_marker(raw):
            continue
        if not isinstance(raw, dict):
            cleaned[key] = raw
            continue
        entry = {field: value for field, value in raw.items() if field not in _INPUT_DERIVED_KEYS}
        message = entry.get("value")
        if isinstance(message, dict) and _wraps_html(message):
            entry["value"] = {field: value for field, value in message.items() if field != "design"}
        cleaned[key] = entry
    return cleaned


def _wraps_html(message: dict[str, Any]) -> bool:
    design = message.get("design")
    return isinstance(design, dict) and design == build_html_wrap_design(message.get("html") or "")


def _ordered(value: Any) -> Any:
    """Plain data in model field order with the identity fields first, leaving out fields at their default."""
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    if not isinstance(value, BaseModel):
        return value
    if isinstance(value, EmailRecipient) and not value.name:
        return value.email
    fields = type(value).model_fields
    names = sorted(fields, key=_field_rank)
    plain: dict[str, Any] = {}
    for name in names:
        field = fields[name]
        field_value = getattr(value, name)
        if not field.is_required() and field_value == field.get_default(call_default_factory=True):
            continue
        plain[field.alias or name] = _ordered(field_value)
    return plain


def _field_rank(name: str) -> int:
    if name in _LEADING_FIELDS:
        return _LEADING_FIELDS.index(name)
    return len(_LEADING_FIELDS) + (1 if name in _TRAILING_FIELDS else 0)


@frozen
class _Placement:
    action: dict[str, Any]
    arms: tuple[tuple["_Placement", ...], ...] | None = None


class _Renderer:
    def __init__(self, definition: dict[str, Any]) -> None:
        self.definition = definition
        self.warnings: list[RenderWarning] = []
        self.visited: set[str] = set()
        self.replacement_ids: set[str] = set()
        self.actions: dict[str, dict[str, Any]] = {}
        for action in _list(definition.get("actions")):
            if isinstance(action, dict) and isinstance(action.get("id"), str):
                self.actions.setdefault(action["id"], action)
        self.trigger_id = next((i for i, a in self.actions.items() if a.get("type") == "trigger"), TRIGGER_NODE_ID)
        self.exit_id = next((i for i, a in self.actions.items() if a.get("type") == "exit"), EXIT_NODE_ID)
        self.continue_to: dict[str, str] = {}
        self.branch_to: dict[str, dict[int, str]] = {}
        for edge in _list(definition.get("edges")):
            if (
                not isinstance(edge, dict)
                or not isinstance(edge.get("from"), str)
                or not isinstance(edge.get("to"), str)
            ):
                continue
            if edge.get("type") == "branch" and isinstance(edge.get("index"), int):
                self.branch_to.setdefault(edge["from"], {}).setdefault(edge["index"], edge["to"])
            elif edge.get("type") == "continue":
                self.continue_to.setdefault(edge["from"], edge["to"])

    def warn(self, action_id: str | None, message: str) -> None:
        self.warnings.append(RenderWarning(action_id=action_id, message=message))

    def name_of(self, action: dict[str, Any]) -> str:
        name = action.get("name")
        return name if isinstance(name, str) and name else action["id"]

    def label(self, action_id: str) -> str:
        if action_id == self.exit_id:
            return "the exit"
        action = self.actions.get(action_id)
        return f'"{self.name_of(action)}"' if action else f"the missing step {action_id}"

    def render(self, key: str | None) -> RenderedWorkflow:
        definition = self.definition
        name = definition.get("name") or "Workflow"
        if not definition.get("name"):
            self.warn(
                None, "The workflow has no name, so the file calls it Workflow. Applying the file names it Workflow."
            )
        status = self.render_status(definition.get("status"))
        if not key:
            key = key_from_name(name)
            status = HogFlow.State.DRAFT
            self.warn(
                None,
                f"This workflow has no key, so the file uses {key}, made from its name. Applying the file creates a second workflow with this key, or updates the one that already has it, and this workflow keeps running. The file says status: draft, so the two never run side by side. To run the workflow from the file, archive this one in PostHog, then set status: active in the file.",
            )
        if definition.get("draft"):
            self.warn(
                None,
                "The workflow has a staged draft, and the file holds the live workflow without it. A change applied through the API replaces the draft.",
            )
        self.warn_renamed_node(self.trigger_id, TRIGGER_NODE_ID, "trigger")
        self.warn_renamed_node(self.exit_id, EXIT_NODE_ID, "exit")
        trigger = self.render_trigger(self.actions.get(self.trigger_id))
        start = self.continue_to.get(self.trigger_id)
        placements = self.walk(start, self.exit_id, "the trigger", 0) if start and start != self.exit_id else ()
        for action_id, action in self.actions.items():
            if action_id not in self.visited and action_id not in (self.trigger_id, self.exit_id):
                self.warn(
                    action_id, f'"{self.name_of(action)}" is not reached from the trigger, so the file leaves it out.'
                )
        steps = [step for placement in placements if (step := self.render_step(placement)) is not None]
        exit_action = _dict(self.actions.get(self.exit_id))
        if exit_action:
            self.warn_action_fields(exit_action, _NODE_FIELDS)
            self.warn_config_fields(exit_action, {"reason"})
        for field in _NOT_IN_THE_FILE:
            if _is_set(definition.get(field)):
                self.warn(
                    None,
                    f"The workflow sets {field}, which a file does not carry. Applying the file keeps the stored value.",
                )
        document = WorkflowDocument.model_validate(
            {
                "version": 1,
                "key": key,
                "name": name,
                "description": definition.get("description") or "",
                "status": status,
                "exit_condition": definition.get("exit_condition") or HogFlow.ExitCondition.ONLY_AT_END.value,
                "variables": self.render_variables(),
                "trigger": trigger,
                "steps": steps,
                "exit": {
                    "name": exit_action.get("name") or "Exit",
                    "reason": _dict(exit_action.get("config")).get("reason") or "",
                    "description": exit_action.get("description") or "",
                },
            }
        )
        data = _ordered(document)
        self.warn_past_the_loader_limits(_shape(data))
        content = dump_workflow_file(data, [warning.message for warning in self.warnings])
        size = len(content.encode("utf-8"))
        if size > MAX_CONTENT_BYTES:
            self.warn(
                None,
                f"The file is {size} bytes, and check and apply refuse a file over {MAX_CONTENT_BYTES} bytes. {_SHRINK_IT}",
            )
            content = dump_workflow_file(data, [warning.message for warning in self.warnings])
        return RenderedWorkflow(content=content, warnings=tuple(self.warnings))

    def warn_past_the_loader_limits(self, shape: _Shape) -> None:
        if shape.depth > MAX_DEPTH:
            self.warn(
                None,
                f"A value in this workflow nests more than {MAX_DEPTH} levels deep in the file, and check and apply refuse a file that deep. Make that value shallower in PostHog before you pull the workflow again.",
            )
        if shape.values > MAX_VALUES:
            self.warn(
                None,
                f"The file holds more than {MAX_VALUES} values, and check and apply refuse a file with that many. {_SHRINK_IT}",
            )

    def warn_renamed_node(self, stored_id: str, file_id: str, label: str) -> None:
        if stored_id in self.actions and stored_id != file_id:
            self.warn(
                stored_id,
                f"The {label} has the id {stored_id}, and a file always calls it {file_id}. Applying the file replaces {stored_id} with {file_id}.",
            )

    def render_status(self, stored: Any) -> str:
        if stored in _DOCUMENT_STATUSES:
            return str(stored)
        self.warn(
            None,
            f"The workflow is {stored}, and a file can only say draft or active. The file says draft, and PostHog refuses to apply it until someone restores it in PostHog.",
        )
        return HogFlow.State.DRAFT

    def render_variables(self) -> list[Variable]:
        variables = []
        for variable in _list(self.definition.get("variables")):
            variable = _dict(variable)
            try:
                rendered = Variable.model_validate(
                    {field: variable[field] for field in ("key", "type", "default") if field in variable}
                )
            except ValidationError:
                self.warn(
                    None,
                    f"The variable {variable.get('key')} has a type or default a file cannot carry, so the file leaves it out.",
                )
                continue
            variables.append(rendered)
            unset = [field for field in ("type", "default") if field not in variable]
            if unset:
                self.warn(
                    None,
                    f"The variable {rendered.key} has no {' or '.join(unset)}. Applying the file stores it with type {rendered.type} and the default '{rendered.default}'.",
                )
            extra = sorted(
                field for field, value in variable.items() if field not in ("key", "type", "default") and _is_set(value)
            )
            if extra:
                self.warn(None, f"The file leaves out {', '.join(extra)} of the variable {variable['key']}.")
        return variables

    def render_trigger(self, trigger: Optional[dict[str, Any]]) -> DocumentTrigger:
        if trigger is None:
            self.warn(
                None,
                "The workflow has no trigger, so the file starts from a schedule trigger. Change it before you apply the file.",
            )
            return _trigger_adapter.validate_python({"type": "schedule"})
        self.warn_action_fields(trigger, _NODE_FIELDS)
        self.warn_secret_inputs(trigger)
        self.warn_credentials(trigger)
        config = _without_filled_in_sources("trigger", _file_config(_dict(trigger.get("config"))))
        base = {"name": self.name_of(trigger), "description": trigger.get("description") or ""}
        kind = config.get("type")
        rest = {key: value for key, value in config.items() if key != "type"}
        if kind in PASS_THROUGH_TRIGGER_TYPES:
            return _trigger_adapter.validate_python({**base, "type": kind, "config": rest})
        typed = self.lossless(_trigger_adapter, _trigger_candidate(base, config), config, trigger_config)
        if typed is not None:
            return typed
        if kind == "event":
            self.warn_config_fields(trigger, {"type", "filters"})
            return _trigger_adapter.validate_python({**base, "type": "event", "filters": rest.get("filters") or {}})
        self.warn(
            trigger["id"],
            "The file carries only the type of the schedule trigger. Applying the file drops the rest of its config.",
        )
        return _trigger_adapter.validate_python({**base, "type": "schedule"})

    def walk(self, start: str, stop: str, origin: str, depth: int) -> tuple[_Placement, ...]:
        placements: list[_Placement] = []
        node = start
        while node != stop:
            action = self.actions.get(node)
            if action is None or node in (self.exit_id, self.trigger_id) or node in self.visited:
                after = f'"{self.name_of(placements[-1].action)}"' if placements else origin
                self.warn(
                    node,
                    f"The path after {after} goes to {self.label(node)}, which a file cannot place there. Applying the file sends people on this path to {self.label(stop)} instead.",
                )
                break
            self.visited.add(node)
            following = self.continue_to.get(node)
            arms = None
            if self.arm_count(action):
                arms = self.walk_arms(action, following or self.exit_id, depth + 1)
            placements.append(_Placement(action=action, arms=arms))
            if following is None:
                self.warn(
                    node,
                    f'"{self.name_of(action)}" leads nowhere. Applying the file connects it to {self.label(stop)}.',
                )
                break
            node = following
        return tuple(placements)

    def arm_count(self, action: dict[str, Any]) -> int:
        kind = action.get("type")
        if kind == "wait_until_condition":
            return 1
        count_key = _BRANCH_COUNT_KEYS.get(kind or "")
        return len(_list(_dict(action.get("config")).get(count_key))) if count_key else 0

    def walk_arms(self, action: dict[str, Any], rejoin: str, depth: int) -> tuple[tuple[_Placement, ...], ...]:
        name = f'"{self.name_of(action)}"'
        if depth > MAX_BRANCH_DEPTH:
            self.warn(
                action["id"],
                f"The branches of {name} are nested more than {MAX_BRANCH_DEPTH} deep, so the file leaves the steps in them out.",
            )
            return tuple(() for _ in range(self.arm_count(action)))
        targets = self.branch_to.get(action["id"], {})
        arms = []
        for index in range(self.arm_count(action)):
            target = targets.get(index)
            if target is None:
                self.warn(
                    action["id"],
                    f"Branch {index + 1} of {name} has no edge. Applying the file connects it to {self.label(rejoin)}.",
                )
            arms.append(self.walk(target, rejoin, name, depth) if target is not None and target != rejoin else ())
        return tuple(arms)

    def render_step(self, placement: _Placement) -> DocumentStep | None:
        action = placement.action
        self.warn_action_fields(action, _STEP_FIELDS)
        self.warn_secret_inputs(action)
        self.warn_credentials(action)
        arms = [
            [step for entry in arm if (step := self.render_step(entry)) is not None] for arm in placement.arms or ()
        ]
        base = self.step_base(action)
        config = _without_filled_in_sources(action.get("type"), _file_config(_dict(action.get("config"))))
        candidate = _step_candidate(action.get("type"), base, config, arms)
        typed = self.lossless(
            _step_adapter, candidate, {"type": action.get("type"), "config": config}, step_action_body
        )
        if typed is not None:
            return typed
        if candidate is not None:
            self.warn(action["id"], _plain_step_reason(self.name_of(action), candidate["type"], config))
        passthrough = {**base, "type": "step", "action_type": action.get("type"), "config": config}
        if arms:
            passthrough["branches"] = arms
        try:
            return _step_adapter.validate_python(passthrough)
        except ValidationError:
            self.warn(
                action["id"],
                f'"{self.name_of(action)}" has a type or name a file cannot hold, so the file leaves it out.',
            )
            return None

    def step_base(self, action: dict[str, Any]) -> dict[str, Any]:
        base: dict[str, Any] = {"name": self.name_of(action), "description": action.get("description") or ""}
        if isinstance(action.get("output_variable"), dict | list):
            base["output_variable"] = action["output_variable"]
        if slug(base["name"]) == action["id"]:
            return base
        if re.fullmatch(STEP_ID_PATTERN, action["id"]):
            return {**base, "id": action["id"]}
        replacement = self.unused_id(slug(base["name"])[: _MAX_STEP_ID_LENGTH - 10] or "step")
        self.warn(
            action["id"],
            f'The id of "{self.name_of(action)}" has characters a file cannot hold, so the file gives the step the id {replacement}. Applying the file moves the people in it on as if the step were removed.',
        )
        return {**base, "id": replacement}

    def unused_id(self, wanted: str) -> str:
        candidate, number = wanted, 1
        while candidate in self.actions or candidate in self.replacement_ids:
            number += 1
            candidate = f"{wanted}_{number}"
        self.replacement_ids.add(candidate)
        return candidate

    def lossless(
        self,
        adapter: TypeAdapter,
        candidate: dict[str, Any] | None,
        stored: dict[str, Any],
        compile_back: Callable[[Any], dict[str, Any]],
    ) -> Any:
        """The typed model for `candidate` when compiling it gives back `stored`, else None."""
        if candidate is None:
            return None
        try:
            model = adapter.validate_python(candidate)
        except ValidationError:
            return None
        return model if _file_config(compile_back(model)) == stored else None

    def warn_action_fields(self, action: dict[str, Any], carried: frozenset[str]) -> None:
        for field in sorted(action.keys() - carried):
            if _is_set(action.get(field)):
                self.warn(
                    action["id"],
                    f'"{self.name_of(action)}" sets {field}, which a file cannot carry. Applying the file removes it.',
                )

    def warn_config_fields(self, action: dict[str, Any], carried: set[str]) -> None:
        config = _dict(action.get("config"))
        dropped = sorted(field for field in config.keys() - carried if _is_set(config[field]))
        if dropped:
            self.warn(
                action["id"],
                f'The config of "{self.name_of(action)}" sets {", ".join(dropped)}, which a file cannot carry. Applying the file removes it.',
            )

    def warn_credentials(self, action: dict[str, Any]) -> None:
        for found in _credential_names(_dict(_dict(action.get("config")).get("inputs"))):
            self.warn(
                action["id"],
                f'The file carries {found} of "{self.name_of(action)}" as plain text. It looks like a credential, and the template does not mark it secret. Take it out before you commit the file. Applying a file without it removes it from the workflow.',
            )

    def warn_secret_inputs(self, action: dict[str, Any]) -> None:
        for key, value in _dict(_dict(action.get("config")).get("inputs")).items():
            if _is_secret_marker(value):
                self.warn(
                    action["id"],
                    f'The input {key} of "{self.name_of(action)}" is a secret. The file leaves it out, and applying the file keeps the stored value.',
                )


def _plain_step_reason(name: str, typed: str, config: dict[str, Any]) -> str:
    message = _dict(_dict(_dict(config.get("inputs")).get("email")).get("value"))
    if typed == "email" and "design" in message:
        return f'The email design of "{name}" was made in the email editor, and a file builds the design from html. The file writes "{name}" as type: step with its whole config, so the design stays.'
    return f'The file writes "{name}" as type: step with its whole config, because a step of type {typed} cannot hold all of it.'


def _condition(entry: Any) -> dict[str, Any] | None:
    entry = _dict(entry)
    kind = entry.get("type")
    if kind not in ("person", "event") or not isinstance(entry.get("key"), str):
        return None
    condition = {kind: entry["key"], "operator": entry.get("operator", "exact")}
    if entry.get("value") is not None:
        condition["value"] = entry["value"]
    return condition


def _trigger_candidate(base: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    if config.get("type") == "schedule":
        return {**base, "type": "schedule"}
    filters = _dict(config.get("filters"))
    events = [event for event in _list(filters.get("events")) if isinstance(event, dict)]
    if config.get("type") != "event" or not events or not isinstance(events[0].get("id"), str):
        return None
    return {
        **base,
        "type": "event",
        "event": events[0]["id"],
        "properties": [_condition(entry) for entry in _list(events[0].get("properties"))],
        "filter_test_accounts": filters.get("filter_test_accounts") is True,
    }


def _step_candidate(
    kind: Any, base: dict[str, Any], config: dict[str, Any], arms: list[list[DocumentStep]]
) -> dict[str, Any] | None:
    if kind == "delay":
        return {**base, "type": "delay", "duration": config.get("delay_duration")}
    if kind == "conditional_branch":
        return {
            **base,
            "type": "branch",
            "arms": [
                {
                    "name": _dict(condition).get("name", ""),
                    "when": [
                        _condition(entry) for entry in _list(_dict(_dict(condition).get("filters")).get("properties"))
                    ],
                    "then": arm,
                }
                for condition, arm in zip(_list(config.get("conditions")), arms)
            ],
        }
    if kind == "function_email":
        return _email_candidate(base, config)
    if kind == "function":
        return _function_candidate(base, config)
    return None


def _function_candidate(base: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    template_id = config.get("template_id")
    values = {}
    for key, raw in _dict(config.get("inputs")).items():
        if not isinstance(raw, dict) or set(raw) != {"value"}:
            return None
        values[key] = raw["value"]
    if not isinstance(template_id, str):
        return None
    if template_id == WEBHOOK_TEMPLATE_ID and "url" in values and set(values) <= {"url", "method", "headers", "body"}:
        return {**base, "type": "webhook", **values}
    return {**base, "type": "function", "template": template_id, "inputs": values}


def _email_candidate(base: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    if config.get("template_id") != EMAIL_TEMPLATE_ID:
        return None
    message = _dict(_dict(_dict(config.get("inputs")).get("email")).get("value"))
    sender = _dict(message.get("from"))
    recipient = _dict(message.get("to"))
    candidate: dict[str, Any] = {
        **base,
        "type": "email",
        "from": {
            "integration_ids": sender.get("integrationIds"),
            **{field: sender[field] for field in ("name", "email") if field in sender},
        },
        "to": recipient.get("email") if recipient.get("name", "") == "" else recipient,
        "subject": message.get("subject"),
    }
    candidate.update({field: message[field] for field in ("text", "html", "preheader") if field in message})
    return candidate
