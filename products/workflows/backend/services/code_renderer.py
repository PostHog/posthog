from __future__ import annotations

import re
import json
from collections.abc import Iterator
from typing import Any

from posthog.cdp.validation import build_html_wrap_design
from posthog.dataclasses import frozen

PACKAGE = "@posthog/workflows"
TRIGGER_ID = "trigger_node"
EXIT_ID = "exit_node"

_INDENT = "    "
_INLINE_WIDTH = 80

_DERIVED_INPUT_KEYS = frozenset({"bytecode", "bytecode_error", "transpiled", "order", "secret"})
_DERIVED_FILTER_KEYS = frozenset({"bytecode", "bytecode_error", "source"})
_CONDITION_CONSTRUCTORS = {"person": "person", "event": "eventProperty", "group": "group"}
_SET_OPERATORS = frozenset({"is_set", "is_not_set"})
_WEBHOOK_INPUTS = frozenset({"url", "method", "body", "headers", "signing_secret"})
_WEBHOOK_METHODS = frozenset({"POST", "PUT", "PATCH", "GET", "DELETE"})
_VARIABLE_TYPES = frozenset({"string", "number", "boolean"})
_SDK_EXIT_CONDITIONS = frozenset({"exit_only_at_end", "exit_on_trigger_not_matched"})
_DEFAULT_EXIT_CONDITION = "exit_only_at_end"
_EXIT_CONDITION_WITHOUT_CONVERSION = {
    "exit_on_conversion": "exit_only_at_end",
    "exit_on_trigger_not_matched_or_conversion": "exit_on_trigger_not_matched",
}
_HOISTABLE_TYPES = frozenset({"delay", "function", "function_email"})

MAX_ACTIONS = 1000
MAX_EDGES = 2000
MAX_BRANCH_ARMS = 100

_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_DURATION = re.compile(r"(?P<amount>[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?P<unit>[dhms])")
_DURATION_CAPS = {"d": 30, "h": 24, "m": 60, "s": 60}
_REPEAT_ID = re.compile(r"(?P<base>.+)_(?P<count>\d+)")
_JS_RESERVED = frozenset(
    "break case catch class const continue debugger default delete do else enum export extends false "
    "finally for function if import in instanceof new null return super switch this throw true try "
    "typeof var void while with yield let static await".split()
)


@frozen
class CodeWarning:
    action_id: str | None
    message: str


@frozen
class RenderedWorkflowCode:
    code: str
    warnings: tuple[CodeWarning, ...]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def branch_arm_count(action: dict[str, Any]) -> int:
    kind = action.get("type")
    config = _dict(action.get("config"))
    if kind == "conditional_branch":
        return len(_list(config.get("conditions")))
    if kind == "random_cohort_branch":
        return len(_list(config.get("cohorts")))
    if kind == "wait_until_condition":
        return 1
    return 0


class WorkflowTooLargeToRender(ValueError):
    pass


def render_workflow_code(definition: dict[str, Any]) -> RenderedWorkflowCode:
    actions = _list(definition.get("actions"))
    if len(actions) > MAX_ACTIONS:
        raise WorkflowTooLargeToRender(f"The workflow has more than {MAX_ACTIONS} steps.")
    if len(_list(definition.get("edges"))) > MAX_EDGES:
        raise WorkflowTooLargeToRender(f"The workflow has more than {MAX_EDGES} edges.")
    if any(isinstance(action, dict) and branch_arm_count(action) > MAX_BRANCH_ARMS for action in actions):
        raise WorkflowTooLargeToRender(f"A step of the workflow has more than {MAX_BRANCH_ARMS} branch arms.")
    return _Renderer(definition).render()


@frozen(kw_only=False)
class _Call:
    name: str
    args: tuple[Any, ...]


@frozen(kw_only=False)
class _Identifier:
    name: str


@frozen(kw_only=False)
class _Comment:
    lines: tuple[str, ...]


def _quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    )
    escaped = re.sub(
        r"[\x00-\x1f\u2028\u2029]",
        lambda match: f"\\x{ord(match.group(0)):02x}" if ord(match.group(0)) < 128 else f"\\u{ord(match.group(0)):04x}",
        escaped,
    )
    return f"'{escaped}'"


def _key(key: str) -> str:
    return key if _IDENTIFIER.fullmatch(key) else _quote(key)


def _comment_line(indent: str, text: str) -> str:
    safe = re.sub(r"[\n\r\u2028\u2029]", lambda match: f"\\u{ord(match.group(0)):04x}", text)
    return f"{indent}// {safe}".rstrip()


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, int | float):
        return repr(value)
    raise TypeError(f"Cannot print {type(value).__name__} as TypeScript")


def _is_primitive(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _inline(node: Any) -> str | None:
    if isinstance(node, _Identifier):
        return node.name
    if isinstance(node, _Comment):
        return None
    if isinstance(node, _Call):
        args = [_inline(arg) for arg in node.args]
        return None if any(arg is None for arg in args) else f"{node.name}({', '.join(args)})"  # type: ignore[arg-type]
    if isinstance(node, list):
        items = [_inline(item) for item in node]
        if any(item is None for item in items):
            return None
        return f"[{', '.join(items)}]" if items else "[]"  # type: ignore[arg-type]
    if isinstance(node, dict):
        pairs = []
        for key, value in node.items():
            printed = _inline(value)
            if printed is None:
                return None
            pairs.append(f"{_key(key)}: {printed}")
        return f"{{ {', '.join(pairs)} }}" if pairs else "{}"
    return _literal(node)


def _print(node: Any, indent: str) -> str:
    inline = _inline(node)
    if inline is not None and len(inline) <= _INLINE_WIDTH:
        return inline
    inner = indent + _INDENT
    if isinstance(node, _Call):
        if node.args and isinstance(node.args[-1], dict) and all(_is_primitive(arg) for arg in node.args[:-1]):
            leading = "".join(f"{_literal(arg)}, " for arg in node.args[:-1])
            return f"{node.name}({leading}{_print(node.args[-1], indent)})"
        return f"{node.name}(\n{_items(node.args, inner)}{indent})"
    if isinstance(node, list):
        return f"[\n{_items(node, inner)}{indent}]"
    if isinstance(node, dict):
        lines: list[str] = []
        for key, value in node.items():
            if isinstance(value, _Comment):
                lines.extend(_comment_line(inner, line) for line in value.lines)
            else:
                lines.append(f"{inner}{_key(key)}: {_print(value, inner)},")
        return "{\n" + "\n".join(lines) + f"\n{indent}}}"
    if inline is None:
        raise TypeError("A comment can only sit inside a list or an object")
    return inline


def _items(items: tuple[Any, ...] | list[Any], indent: str) -> str:
    lines: list[str] = []
    for item in items:
        if isinstance(item, _Comment):
            lines.extend(_comment_line(indent, line) for line in item.lines)
        else:
            lines.append(f"{indent}{_print(item, indent)},")
    return "".join(f"{line}\n" for line in lines)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _kebab(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workflow"


def _camel(text: str, fallback: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", text) if part]
    if not parts:
        return fallback
    name = parts[0].lower() + "".join(part[:1].upper() + part[1:] for part in parts[1:])
    if name[0].isdigit():
        name = fallback + name[:1].upper() + name[1:]
    return name + "Step" if name in _JS_RESERVED else name


def _env_name(action_id: str, input_key: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "_", f"{action_id}_{input_key}").strip("_").upper()
    return name if name and not name[0].isdigit() else f"SECRET_{name}"


def _json_lines(value: Any) -> tuple[str, ...]:
    return tuple(json.dumps(value, indent=4, ensure_ascii=False).splitlines())


def _is_set(value: Any) -> bool:
    if value is None or isinstance(value, bool | int | float):
        return value is not None
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_is_set(entry) for entry in value.values())
    if isinstance(value, list | tuple):
        return any(_is_set(entry) for entry in value)
    return True


@frozen
class _Placement:
    action: dict[str, Any]
    arms: tuple[tuple[_Placement, ...], ...] | None = None

    @property
    def id(self) -> str:
        return self.action["id"]

    @property
    def name(self) -> str:
        name = self.action.get("name")
        return name if isinstance(name, str) and name else self.id


class _Renderer:
    def __init__(self, definition: dict[str, Any]) -> None:
        self.definition = definition
        self.warnings: list[CodeWarning] = []
        self.imports: set[str] = set()
        self.visited: set[str] = set()
        self.dropped: set[str] = set()
        self.kept_arms: dict[str, list[int]] = {}
        self.edgeless_arms: dict[str, set[int]] = {}
        self.pass_through: list[str] = []
        self.secret_owner: dict[str, str] = {}
        self.calls: dict[str, _Call] = {}
        self.comments: dict[str, _Comment] = {}
        self.repeats: dict[str, str] = {}
        self.hoisted: list[str] = []
        self.const_names: dict[str, str] = {}
        self.const_definitions: list[tuple[str, str]] = []

        actions = definition.get("actions")
        self.actions: dict[str, dict[str, Any]] = {}
        for action in actions if isinstance(actions, list) else []:
            if isinstance(action, dict) and isinstance(action.get("id"), str):
                self.actions.setdefault(action["id"], action)
        self.trigger_id = next(
            (action_id for action_id, action in self.actions.items() if action.get("type") == "trigger"), TRIGGER_ID
        )
        self.exit_id = next(
            (action_id for action_id, action in self.actions.items() if action.get("type") == "exit"), EXIT_ID
        )
        self.continue_to: dict[str, str] = {}
        self.branch_to: dict[str, dict[int, str]] = {}
        stray_branches: dict[str, int] = {}
        edges = definition.get("edges")
        for edge in edges if isinstance(edges, list) else []:
            if (
                not isinstance(edge, dict)
                or not isinstance(edge.get("from"), str)
                or not isinstance(edge.get("to"), str)
            ):
                continue
            if edge.get("type") == "branch" and isinstance(edge.get("index"), int):
                source = self.actions.get(edge["from"])
                if source is not None and 0 <= edge["index"] < branch_arm_count(source):
                    self.branch_to.setdefault(edge["from"], {}).setdefault(edge["index"], edge["to"])
                elif source is not None:
                    stray_branches[edge["from"]] = stray_branches.get(edge["from"], 0) + 1
            elif edge.get("type") == "continue":
                self.continue_to.setdefault(edge["from"], edge["to"])
        for action_id, count in stray_branches.items():
            self.warn(
                action_id,
                f'"{self._name(self.actions[action_id])}" has {count} branch edge(s) that match no arm of the step. They are dropped.',
            )

    def warn(self, action_id: str | None, message: str) -> None:
        self.warnings.append(CodeWarning(action_id=action_id, message=message))

    def use(self, name: str) -> str:
        self.imports.add(name)
        return name

    def walk(self, start: str, stop: str) -> tuple[_Placement, ...]:
        placements: list[_Placement] = []
        node = start
        while node != stop:
            action = self.actions.get(node)
            if action is None or node == self.exit_id or node in self.visited:
                previous = placements[-1].name if placements else start
                self.warn(
                    node,
                    f'The path after "{previous}" does not rejoin the workflow. The steps it leads to are dropped.',
                )
                break
            self.visited.add(node)
            following = self.continue_to.get(node)
            if following is None:
                self.warn(
                    node,
                    f'"{self._name(action)}" leads nowhere. The path stops there and a push adds the exit after it.',
                )
                arms = self.walk_arms(action, self.exit_id) if action.get("type") == "conditional_branch" else None
                placements.append(_Placement(action=action, arms=arms))
                break
            arms = None
            if self.branch_to.get(node):
                arms = self.walk_arms(action, following)
            placements.append(_Placement(action=action, arms=arms))
            node = following
        return tuple(placements)

    def walk_arms(self, action: dict[str, Any], rejoin: str) -> tuple[tuple[_Placement, ...], ...]:
        targets = self.branch_to.get(action["id"], {})
        conditions = _list(_dict(action.get("config")).get("conditions"))
        arms: list[tuple[_Placement, ...]] = []
        for index in range(branch_arm_count(action)):
            condition = conditions[index] if index < len(conditions) else None
            target = targets.get(index)
            arm_name = condition.get("name") if isinstance(condition, dict) else None
            if target is None:
                self.warn(
                    action["id"],
                    f'The arm "{arm_name or index}" of "{self._name(action)}" has no edge. Add a step to it before you push.',
                )
                self.edgeless_arms.setdefault(action["id"], set()).add(index)
                arms.append(())
            else:
                arms.append(self.walk(target, rejoin))
        return tuple(arms)

    @staticmethod
    def _name(action: dict[str, Any]) -> str:
        name = action.get("name")
        return name if isinstance(name, str) and name else action["id"]

    def droppable_arms(
        self, action_id: str, arms: tuple[tuple[_Placement, ...], ...], arm_count: int, *, conditions_follow: bool
    ) -> set[int]:
        edgeless = self.edgeless_arms.get(action_id, set()) | set(range(len(arms), arm_count))
        droppable: set[int] = set()
        for index in reversed(range(arm_count)):
            if index < len(arms) and arms[index]:
                break
            if not conditions_follow and index not in edgeless:
                break
            droppable.add(index)
        return droppable

    def warn_kept_empty_arm(self, action: dict[str, Any], index: int, arm_name: Any) -> None:
        if index in self.edgeless_arms.get(action["id"], set()):
            return
        self.warn(
            action["id"],
            f'The arm "{arm_name}" of "{self._name(action)}" has no steps. {PACKAGE} cannot declare an empty arm, and leaving it out would send a person who matches it and a later arm down the later arm. The file keeps it as an empty path(), which does not push. Add a step to the arm or remove it in PostHog first.',
        )

    @classmethod
    def _base_options(cls, action: dict[str, Any]) -> dict[str, Any]:
        options: dict[str, Any] = {"name": cls._name(action)}
        description = action.get("description")
        if _is_set(description):
            options["description"] = description
        return options

    @staticmethod
    def _flatten(placements: tuple[_Placement, ...]) -> Iterator[_Placement]:
        for placement in placements:
            yield placement
            for arm in placement.arms or ():
                yield from _Renderer._flatten(arm)

    def render_step(self, placement: _Placement) -> None:
        action = placement.action
        if action["id"] in self.dropped:
            return
        kind = action.get("type")
        config = _dict(action.get("config"))
        call: _Call | None = None
        if self.needs_pass_through(action, config, placement.arms):
            call = self.render_pass_through_step(action, config, placement.arms or ())
        elif kind == "delay":
            call = self.render_delay(action, config)
        elif kind == "function":
            call = self.render_function(action, config)
        elif kind == "function_email":
            call = self.render_email(action, config)
        elif kind == "conditional_branch":
            imports = set(self.imports)
            call = self.render_branch(action, config, placement.arms or ())
            if call is None or call.name != "branch":
                self.imports = imports
                if call is not None:
                    self.use(call.name)
        if call is None:
            call = self.render_pass_through_step(action, config, placement.arms or ())
        self.calls[action["id"]] = call

    def needs_pass_through(
        self, action: dict[str, Any], config: dict[str, Any], arms: tuple[tuple[_Placement, ...], ...] | None
    ) -> bool:
        kind = action.get("type")
        if kind not in {"delay", "function", "function_email", "conditional_branch"}:
            return True
        if arms is not None and kind != "conditional_branch":
            return True
        filters = action.get("filters")
        if isinstance(filters, dict) and _is_set(filters):
            return True
        if _is_set(action.get("on_error")) or _is_set(action.get("output_variable")):
            return True
        if kind == "delay":
            duration = config.get("delay_duration")
            match = _DURATION.fullmatch(duration) if isinstance(duration, str) else None
            return (
                set(config) != {"delay_duration"}
                or match is None
                or float(match["amount"]) == 0
                or float(match["amount"]) > _DURATION_CAPS[match["unit"]]
            )
        if kind == "function_email":
            return self.email_needs_pass_through(action, config)
        return False

    def warn_extra_config(self, action: dict[str, Any], config: dict[str, Any], known: frozenset[str]) -> None:
        for key, value in config.items():
            if key not in known and value not in (None, "", [], {}):
                self.warn(
                    action["id"],
                    f'The setting "{key}" of "{self._name(action)}" is dropped. {PACKAGE} has no field for it.',
                )

    def pass_through_options(
        self, action: dict[str, Any], config: dict[str, Any], arms: tuple[tuple[_Placement, ...], ...]
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            **self._base_options(action),
            "type": action.get("type"),
            "config": self.render_config(action, config),
        }
        for key in ("filters", "on_error", "output_variable"):
            if _is_set(action.get(key)):
                options[key] = action[key]
        if arms:
            options["branches"] = None
        return options

    def render_pass_through_step(
        self, action: dict[str, Any], config: dict[str, Any], arms: tuple[tuple[_Placement, ...], ...]
    ) -> _Call:
        if arms:
            dropped = self.droppable_arms(action["id"], arms, len(arms), conditions_follow=False)
            kept = [index for index in range(len(arms)) if index not in dropped]
            for index in kept:
                if not arms[index]:
                    self.warn_kept_empty_arm(action, index, index)
            self.kept_arms[action["id"]] = kept
        self.pass_through.append(f"{action['id']} ({self._name(action)})")
        return _Call(self.use("step"), (self.pass_through_options(action, config, arms),))

    def render_config(self, action: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        if isinstance(config.get("inputs"), dict):
            return {**config, "inputs": self.render_inputs(action, config["inputs"], keep_wrappers=True)}
        return config

    def render_delay(self, action: dict[str, Any], config: dict[str, Any]) -> _Call | None:
        duration = config.get("delay_duration")
        if not isinstance(duration, str) or not duration:
            return None
        match = _DURATION.fullmatch(duration)
        if match is None or float(match["amount"]) == 0 or float(match["amount"]) > _DURATION_CAPS[match["unit"]]:
            self.warn(
                action["id"],
                f'"{self._name(action)}" waits for "{duration}", which {PACKAGE} refuses at push. Write a positive amount up to 60s, 60m, 24h or 30d.',
            )
        self.warn_extra_config(action, config, frozenset({"delay_duration"}))
        return _Call(self.use("delay"), (duration, self._base_options(action)))

    def secret_base(self, action: dict[str, Any]) -> str:
        match = _REPEAT_ID.fullmatch(action["id"])
        if match and match["count"] == str(int(match["count"])):
            first = self.actions.get(match["base"])
            if (
                first is not None
                and first.get("type") == action.get("type")
                and first.get("config") == action.get("config")
            ):
                return match["base"]
        return action["id"]

    def render_inputs(
        self, action: dict[str, Any], inputs: dict[str, Any], *, keep_wrappers: bool = False
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, raw in inputs.items():
            if isinstance(raw, dict) and raw.get("templating") not in (None, "hog"):
                self.warn(
                    action["id"],
                    f'The input "{key}" of "{self._name(action)}" uses {raw.get("templating")} templating. {PACKAGE} uses Hog templating, so rewrite the input before you push.',
                )
            if isinstance(raw, dict) and raw.get("secret") is True:
                base = self.secret_base(action)
                env = _env_name(base, key)
                owner = self.secret_owner.setdefault(env, base)
                if owner != base:
                    self.warn(
                        action["id"],
                        f'"{self._name(action)}" and "{self._name(self.actions[owner])}" both read {env}. Rename one step so each secret has its own variable.',
                    )
                elif base == action["id"]:
                    self.warn(
                        action["id"],
                        f'The input "{key}" of "{self._name(action)}" is a secret. PostHog does not return its value, so set {env} before you push.',
                    )
                values[key] = _Call(self.use("secret"), (env,))
            elif keep_wrappers:
                values[key] = raw
            elif isinstance(raw, dict) and (
                set(raw) <= _DERIVED_INPUT_KEYS | {"value"}
                or (raw.get("templating") == "hog" and set(raw) <= _DERIVED_INPUT_KEYS | {"value", "templating"})
            ):
                values[key] = raw.get("value")
            else:
                values[key] = raw
        return values

    def render_function(self, action: dict[str, Any], config: dict[str, Any]) -> _Call | None:
        template_id = config.get("template_id")
        if not isinstance(template_id, str) or not template_id:
            return None
        self.warn_extra_config(action, config, frozenset({"template_id", "inputs", "inputs_schema"}))
        values = self.render_inputs(action, _dict(config.get("inputs")))
        webhook = self.render_webhook(action, values) if template_id == "template-webhook" else None
        if webhook is not None:
            return webhook
        return _Call(self.use("fn"), ({**self._base_options(action), "templateId": template_id, "inputs": values},))

    def render_webhook(self, action: dict[str, Any], values: dict[str, Any]) -> _Call | None:
        if set(values) - _WEBHOOK_INPUTS or not isinstance(values.get("url"), str):
            return None
        method = values.get("method", "POST")
        body = values.get("body", {})
        headers = values.get("headers", {})
        signing_secret = values.get("signing_secret")
        if not isinstance(method, str):
            self.warn(
                action["id"],
                f'The webhook method of "{self._name(action)}" is not text. {PACKAGE} cannot declare it as webhook(...), so the function template is kept instead.',
            )
            return None
        if method not in _WEBHOOK_METHODS or not isinstance(body, dict) or not isinstance(headers, dict):
            return None
        if any(not isinstance(value, str) for value in headers.values()):
            return None
        if signing_secret is not None and not isinstance(signing_secret, _Call):
            return None
        options: dict[str, Any] = {**self._base_options(action), "url": values["url"]}
        if method != "POST":
            options["method"] = method
        if body:
            options["body"] = body
        if "headers" in values:
            options["headers"] = headers
        if signing_secret is not None:
            options["signingSecret"] = signing_secret
        return _Call(self.use("webhook"), (options,))

    def email_needs_pass_through(self, action: dict[str, Any], config: dict[str, Any]) -> bool:
        inputs = _dict(config.get("inputs"))
        message = _dict(inputs.get("email")).get("value")
        if not isinstance(message, dict):
            return False
        if any(key != "email" and _is_set(value) for key, value in inputs.items()):
            return True
        sender = _dict(message.get("from"))
        ids = sender.get("integrationIds")
        if not isinstance(ids, list):
            ids = [sender["integrationId"]] if sender.get("integrationId") is not None else []
        if not ids:
            return True
        recipient = message.get("to")
        design = message.get("design")
        html = message.get("html")
        if design is not None and design != build_html_wrap_design(html if isinstance(html, str) else ""):
            return True
        if isinstance(recipient, dict) and _is_set({k: v for k, v in recipient.items() if k != "email"}):
            return True
        for key, value in message.items():
            if key not in ("from", "to", "subject", "text", "html", "design", "preheader") and _is_set(value):
                return True
        return False

    def render_email(self, action: dict[str, Any], config: dict[str, Any]) -> _Call | None:
        inputs = _dict(config.get("inputs"))
        message = _dict(inputs.get("email")).get("value")
        if not isinstance(message, dict):
            return None
        sender = _dict(message.get("from"))
        recipient = message.get("to")
        to = recipient.get("email") if isinstance(recipient, dict) else recipient
        html = message.get("html")
        if not isinstance(to, str) or not isinstance(html, str):
            return None
        name = self._name(action)
        self.warn_extra_config(action, config, frozenset({"template_id", "inputs"}))
        for key in inputs:
            if key != "email":
                self.warn(
                    action["id"],
                    f'The input "{key}" of "{name}" is dropped. An email step in {PACKAGE} takes only the message.',
                )

        ids = sender.get("integrationIds")
        if not isinstance(ids, list):
            ids = [sender["integrationId"]] if sender.get("integrationId") is not None else []
        if not ids:
            self.warn(
                action["id"], f'"{name}" names no sender. Add an integration id to from.integrationIds before you push.'
            )
        from_options: dict[str, Any] = {"integrationIds": ids}
        for key in ("email", "name"):
            if isinstance(sender.get(key), str) and sender[key]:
                from_options[key] = sender[key]

        options: dict[str, Any] = {
            **self._base_options(action),
            "from": from_options,
            "to": to,
            "subject": message.get("subject", ""),
            "text": message.get("text", ""),
            "html": html,
        }
        if isinstance(message.get("preheader"), str) and message["preheader"]:
            options["preheader"] = message["preheader"]
        design = message.get("design")
        if design is not None and design != build_html_wrap_design(html):
            self.warn(
                action["id"],
                f'The email design of "{name}" was edited in the visual editor. {PACKAGE} rebuilds the design from html, so that layout is dropped.',
            )
        if isinstance(recipient, dict) and _is_set({k: v for k, v in recipient.items() if k != "email"}):
            self.warn(
                action["id"],
                f'The recipient of "{name}" carries more than an address. {PACKAGE} sends to the address only.',
            )
        for key, value in message.items():
            if key not in ("from", "to", "subject", "text", "html", "design", "preheader") and _is_set(value):
                self.warn(
                    action["id"],
                    f'The field "{key}" of the email in "{name}" is dropped. {PACKAGE} has no field for it.',
                )
        return _Call(self.use("email"), (options,))

    def render_condition(self, action_id: str, condition: Any) -> _Call | None:
        if not isinstance(condition, dict):
            return None
        kind = condition.get("type")
        constructor = _CONDITION_CONSTRUCTORS.get(kind) if isinstance(kind, str) else None
        key = condition.get("key")
        operator = condition.get("operator")
        if constructor is None or not isinstance(key, str) or not isinstance(operator, str):
            return None
        allowed = {"key", "operator", "type", "value"}
        if kind == "group":
            allowed.add("group_type_index")
        for extra in condition:
            if extra not in allowed:
                self.warn(
                    action_id,
                    f'The field "{extra}" of the condition on "{key}" is dropped. {PACKAGE} has no field for it.',
                )
        if operator in _SET_OPERATORS:
            value = condition.get("value")
            if value not in (None, operator):
                self.warn(
                    action_id,
                    f'The condition on "{key}" uses "{operator}" but also has a value. {PACKAGE} ignores that value for this operator.',
                )
            if kind == "group":
                group_type_index = condition.get("group_type_index")
                if not isinstance(group_type_index, int):
                    return None
                return _Call(self.use("group"), (group_type_index, key, operator))
            return _Call(self.use(constructor), (key, operator))
        if condition.get("value") is None:
            return None
        if kind == "group":
            group_type_index = condition.get("group_type_index")
            if not isinstance(group_type_index, int):
                return None
            return _Call(self.use("group"), (group_type_index, key, operator, condition["value"]))
        return _Call(self.use(constructor), (key, operator, condition["value"]))

    def render_branch(
        self, action: dict[str, Any], config: dict[str, Any], placed_arms: tuple[tuple[_Placement, ...], ...]
    ) -> _Call | None:
        conditions = config.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            return None
        self.warn_extra_config(action, config, frozenset({"conditions"}))
        dropped = self.droppable_arms(action["id"], placed_arms, len(conditions), conditions_follow=True)
        arms = []
        kept: list[int] = []
        dropped_names: list[Any] = []
        empty_kept: list[tuple[int, Any]] = []
        for index, condition in enumerate(conditions):
            if not isinstance(condition, dict):
                return None
            if index in dropped:
                dropped_names.append(condition.get("name", index))
                continue
            if not placed_arms[index]:
                empty_kept.append((index, condition.get("name", index)))
            filters = _dict(condition.get("filters"))
            properties = filters.get("properties")
            if not isinstance(properties, list) or not properties:
                return None
            if any(filters.get(key) for key in filters if key not in _DERIVED_FILTER_KEYS and key != "properties"):
                return None
            if any(isinstance(entry, dict) and entry.get("type") == "event" for entry in properties):
                return self.render_pass_through_step(action, config, placed_arms)
            when = [self.render_condition(action["id"], entry) for entry in properties]
            if any(entry is None for entry in when):
                return self.render_pass_through_step(action, config, placed_arms)
            arms.append({"name": condition.get("name", ""), "when": when, "then": None})
            kept.append(index)
        if not arms:
            return None
        for arm_name in dropped_names:
            self.warn(
                action["id"],
                f'The arm "{arm_name}" of "{self._name(action)}" has no steps, so it is dropped. A person who matches it continues after the branch either way.',
            )
        for index, arm_name in empty_kept:
            self.warn_kept_empty_arm(action, index, arm_name)
        self.kept_arms[action["id"]] = kept
        return _Call(self.use("branch"), ({**self._base_options(action), "branches": arms},))

    def hoist_repeats(self, placements: tuple[_Placement, ...]) -> None:
        count_of_base: dict[str, int] = {}
        for placement in placements:
            action_id = placement.id
            call = self.calls.get(action_id)
            if call is None or placement.action.get("type") not in _HOISTABLE_TYPES:
                continue
            match = _REPEAT_ID.fullmatch(action_id)
            if match and match["base"] in count_of_base and match["count"] == str(count_of_base[match["base"]] + 1):
                first = match["base"]
                if _print(call, "") == _print(self.calls[first], ""):
                    count_of_base[first] += 1
                    self.repeats[action_id] = first
                    if first not in self.hoisted:
                        self.hoisted.append(first)
                    continue
            count_of_base[action_id] = 1
        self.hoisted.sort(key=[placement.id for placement in placements].index)

    def name_consts(self, taken: set[str]) -> None:
        for first in self.hoisted:
            name = _camel(first, "step")
            candidate, counter = name, 1
            while candidate in taken:
                counter += 1
                candidate = f"{name}{counter}"
            taken.add(candidate)
            self.const_names[first] = candidate
            source = _print(self.with_id(self.calls[first], self.actions[first]), "")
            self.const_definitions.append((candidate, source))

    @staticmethod
    def with_id(call: _Call, action: dict[str, Any]) -> _Call:
        options = call.args[-1]
        if action["id"] == _slug(options["name"]):
            return call
        leading = {key: options[key] for key in ("name", "description") if key in options}
        return _Call(
            call.name,
            (
                *call.args[:-1],
                {**leading, "id": action["id"], **{k: v for k, v in options.items() if k not in leading}},
            ),
        )

    def node_for(self, placement: _Placement) -> Any:
        action_id = placement.id
        if action_id in self.comments:
            return self.comments[action_id]
        const = self.const_names.get(self.repeats.get(action_id, action_id))
        if const is not None:
            return _Identifier(const)
        call = self.calls[action_id]
        if placement.arms is not None:
            options = call.args[-1]
            if "branches" in options:
                if call.name == "step":
                    options["branches"] = [
                        _Call(self.use("path"), tuple(self.node_for(entry) for entry in placement.arms[index]))
                        for index in self.kept_arms[action_id]
                    ]
                else:
                    for index, spec in zip(self.kept_arms[action_id], options["branches"]):
                        spec["then"] = _Call(
                            self.use("path"), tuple(self.node_for(entry) for entry in placement.arms[index])
                        )
        return self.with_id(call, placement.action)

    def action_options(self, action: dict[str, Any]) -> dict[str, Any]:
        options: dict[str, Any] = {}
        name = self._name(action)
        if name != "Trigger" and action.get("type") == "trigger":
            options["name"] = name
        if name != "Exit" and action.get("type") == "exit":
            options["name"] = name
        description = action.get("description")
        if _is_set(description):
            options["description"] = description
        return options

    def render_raw_trigger(
        self, trigger: dict[str, Any], config: dict[str, Any], trigger_options: dict[str, Any]
    ) -> _Call:
        rendered = self.render_config(trigger, config)
        return _Call(self.use("trigger"), (rendered, trigger_options) if trigger_options else (rendered,))

    def render_trigger(self, trigger: dict[str, Any] | None) -> Any:
        if trigger is None:
            self.warn(self.trigger_id, "The workflow has no trigger step. Add `on` before you push.")
            return _Comment(("Add the trigger here: on: onEvent({ event: '...' }) or on: onSchedule().",))
        config = _dict(trigger.get("config"))
        kind = config.get("type")
        trigger_options = self.action_options(trigger)
        if kind == "schedule":
            return _Call(self.use("onSchedule"), (trigger_options,) if trigger_options else ())
        filters = _dict(config.get("filters"))
        events = [event for event in _list(filters.get("events")) if isinstance(event, dict)]
        if kind == "event" and events and events[0].get("type") == "events" and isinstance(events[0].get("id"), str):
            first = events[0]
            event_properties = first.get("properties") or []
            if (
                not isinstance(event_properties, list)
                or len(events) > 1
                or filters.get("actions")
                or filters.get("properties")
                or filters.get("filter_test_accounts")
            ):
                return self.render_raw_trigger(trigger, config, trigger_options)
            options: dict[str, Any] = {"event": first["id"], **trigger_options}
            properties = []
            for entry in event_properties:
                condition = self.render_condition(self.trigger_id, entry)
                if condition is None:
                    self.warn(
                        self.trigger_id,
                        f"A condition on the trigger event is dropped. {PACKAGE} reads person, event and group properties only.",
                    )
                else:
                    properties.append(condition)
            if properties:
                options["properties"] = properties
            return _Call(self.use("onEvent"), (options,))
        return self.render_raw_trigger(trigger, config, trigger_options)

    def render_variables(self) -> list[dict[str, Any]]:
        variables = self.definition.get("variables")
        rendered = []
        for variable in variables if isinstance(variables, list) else []:
            if not isinstance(variable, dict):
                continue
            key = variable.get("key")
            if variable.get("type") not in _VARIABLE_TYPES:
                self.warn(
                    None,
                    f'The variable "{key}" has the type "{variable.get("type")}", which {PACKAGE} cannot declare. It is dropped.',
                )
                continue
            rendered_variable = {"key": key, "type": variable["type"], "default": variable.get("default", "")}
            if isinstance(variable.get("label"), str):
                rendered_variable["label"] = variable["label"]
            rendered.append(rendered_variable)
        return rendered

    def render(self) -> RenderedWorkflowCode:
        definition = self.definition
        stored_name = definition.get("name")
        name = stored_name if isinstance(stored_name, str) else ""
        stored_key = definition.get("key")
        has_stored_key = isinstance(stored_key, str) and bool(stored_key)
        key = stored_key if isinstance(stored_key, str) and stored_key else _kebab(name)
        if not has_stored_key and key.startswith("replace-me-"):
            key = f"copied-{key.removeprefix('replace-me-')}"
        if not has_stored_key:
            self.warn(
                None,
                "This workflow has no key, so the copied file invents one from its name. The first push creates a new draft workflow. Turn the original workflow off or delete it after that push.",
            )

        start = self.continue_to.get(self.trigger_id)
        if start is None or start == self.exit_id:
            self.warn(self.trigger_id, "The trigger leads to no step. The workflow has no steps.")
            placements: tuple[_Placement, ...] = ()
        else:
            placements = self.walk(start, self.exit_id)
        for action_id, action in self.actions.items():
            if action_id not in self.visited and action_id not in (self.trigger_id, self.exit_id):
                self.warn(action_id, f'"{self._name(action)}" is not reached from the trigger and is dropped.')

        for stored_id, sdk_id, label in ((self.trigger_id, TRIGGER_ID, "trigger"), (self.exit_id, EXIT_ID, "exit")):
            if stored_id in self.actions and stored_id != sdk_id:
                self.warn(
                    stored_id,
                    f'The {label} has the id "{stored_id}", and {PACKAGE} always names it "{sdk_id}". The first push removes "{stored_id}" and adds "{sdk_id}" in its place.',
                )
        on = self.render_trigger(self.actions.get(self.trigger_id))
        flat = tuple(self._flatten(placements))
        for placement in flat:
            self.render_step(placement)
        self.hoist_repeats(flat)

        options: dict[str, Any] = {"key": key, "name": name}
        if definition.get("description"):
            options["description"] = definition["description"]
        conversion = _dict(definition.get("conversion"))
        has_conversion_goal = _is_set(conversion.get("filters")) or _is_set(conversion.get("events"))
        exit_condition = definition.get("exit_condition") or _DEFAULT_EXIT_CONDITION
        declared_exit_condition = exit_condition
        if exit_condition not in _SDK_EXIT_CONDITIONS:
            declared_exit_condition = _EXIT_CONDITION_WITHOUT_CONVERSION.get(exit_condition, _DEFAULT_EXIT_CONDITION)
            if has_conversion_goal:
                self.warn(
                    self.exit_id,
                    f'The exit condition "{exit_condition}" needs a conversion goal, which {PACKAGE} cannot declare. The file declares "{declared_exit_condition}", so a person who converts no longer leaves early.',
                )
            else:
                self.warn(
                    self.exit_id,
                    f'The exit condition "{exit_condition}" is not one {PACKAGE} can declare, so the file declares "{declared_exit_condition}" and the first push stores it. With no conversion goal, the two run the same.',
                )
        if declared_exit_condition != _DEFAULT_EXIT_CONDITION:
            options["exitCondition"] = declared_exit_condition
        variables = self.render_variables()
        if variables:
            options["variables"] = variables
        if has_conversion_goal:
            self.warn(None, f"The conversion goal is dropped. {PACKAGE} cannot declare one.")
        for setting_key in ("email_sending_rate_limit", "schedules", "abort_action"):
            if _is_set(definition.get(setting_key)):
                self.warn(None, f'The workflow setting "{setting_key}" is dropped. {PACKAGE} cannot declare it.')
        if definition.get("trigger_masking"):
            self.warn(self.trigger_id, f"The trigger masking is dropped. {PACKAGE} cannot declare it.")
        options["on"] = on

        exit_action = self.actions.get(self.exit_id)
        reason = ((exit_action or {}).get("config") or {}).get("reason")
        if exit_action is None:
            self.warn(self.exit_id, "The workflow has no exit step. The exit reason is left empty.")

        export_name = _camel(key, "workflow")
        self.use("workflow")
        self.use("path")
        if export_name in self.imports:
            export_name += "Workflow"
        self.name_consts({*self.imports, export_name})
        if placements:
            options["steps"] = _Call("path", tuple(self.node_for(placement) for placement in placements))
        else:
            options["steps"] = _Call(
                "path",
                (
                    _Call(
                        self.use("step"),
                        (
                            {
                                "type": "noop",
                                "name": "No operation",
                                "config": {},
                                "id": "no_operation",
                            },
                        ),
                    ),
                ),
            )
            self.pass_through.append("no_operation (No operation)")
            self.warn(
                None,
                "The workflow has no steps. A no-operation step is added so the file loads, but remove it before you push.",
            )
        exit_options = {"reason": reason if isinstance(reason, str) else ""}
        if exit_action is not None:
            exit_options.update(self.action_options(exit_action))
        options["exit"] = exit_options

        header = []
        if self.warnings or self.pass_through:
            header.append(f"// {PACKAGE} cannot express everything in this workflow. Review these before you push:")
            if self.pass_through:
                header.append(_comment_line("", f"- Pass-through steps: {', '.join(self.pass_through)}."))
            for warning in self.warnings:
                prefix = f"{warning.action_id}: " if warning.action_id else ""
                header.append(_comment_line("", f"- {prefix}{warning.message}"))
            header.append("")
        header.append(f"import {{ {', '.join(sorted(self.imports))} }} from {_quote(PACKAGE)}")
        header.append("")
        for const_name, source in self.const_definitions:
            header.append(f"const {const_name} = {source}")
            header.append("")
        header.append(f"export const {export_name} = {_print(_Call('workflow', (options,)), '')}")
        return RenderedWorkflowCode(code="\n".join(header) + "\n", warnings=tuple(self.warnings))
