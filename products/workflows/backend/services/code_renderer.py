"""Renders a stored workflow as `@posthog/workflows` TypeScript source.

The SDK's `emit.ts` maps source to a definition. This module walks the definition the read API
returns and writes the source back, so the two stay inverses. The golden fixtures under
`products/workflows/backend/test/fixtures/code_renderer/` hold the pairs: each `.json` must render
as its `.ts` byte for byte, and a `.roundtrip.json` holds what that `.ts` emits where it differs
from the stored `.json`.

Everything the SDK cannot express stays visible. A step with no constructor keeps its place in the
path as a commented JSON block, a lost setting becomes a `CodeWarning`, and the file opens with the
warnings as a comment so an agent reading the source alone sees the gaps.
"""

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
# A value whose one-line form is longer than this breaks across lines.
_INLINE_WIDTH = 80

# Keys PostHog stamps on a function input at validation. The SDK's `diff.ts` ignores the same set.
_DERIVED_INPUT_KEYS = frozenset({"bytecode", "bytecode_error", "transpiled", "order", "secret", "templating"})
# Keys PostHog compiles onto a branch condition's filters.
_DERIVED_FILTER_KEYS = frozenset({"bytecode", "bytecode_error", "source"})
_CONDITION_CONSTRUCTORS = {"person": "person", "event": "eventProperty", "group": "group"}
_OPERATORS = frozenset({"exact", "is_not", "icontains", "not_icontains", "is_set", "is_not_set", "gt", "lt"})
_WEBHOOK_INPUTS = frozenset({"url", "method", "body", "headers", "signing_secret"})
_WEBHOOK_METHODS = frozenset({"POST", "PUT", "PATCH", "GET", "DELETE"})
_VARIABLE_TYPES = frozenset({"string", "number", "boolean"})
_SDK_EXIT_CONDITIONS = frozenset({"exit_only_at_end", "exit_on_trigger_not_matched"})
_DEFAULT_EXIT_CONDITION = "exit_only_at_end"
_HOISTABLE_TYPES = frozenset({"delay", "function", "function_email"})

_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
# The same pattern and caps `emit.ts` checks, so a wait the push would refuse is warned about here.
_DURATION = re.compile(r"^(?P<amount>[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?P<unit>[dhms])$")
_DURATION_CAPS = {"d": 30, "h": 24, "m": 60, "s": 60}
_REPEAT_ID = re.compile(r"^(?P<base>.+)_(?P<count>\d+)$")
_JS_RESERVED = frozenset(
    "break case catch class const continue debugger default delete do else enum export extends false "
    "finally for function if import in instanceof new null return super switch this throw true try "
    "typeof var void while with yield let static await".split()
)


@frozen
class CodeWarning:
    """One thing the rendered source does not carry. `action_id` is None for a workflow-level loss."""

    action_id: str | None
    message: str


@frozen
class RenderedWorkflowCode:
    code: str
    warnings: tuple[CodeWarning, ...]


def render_workflow_code(definition: dict[str, Any]) -> RenderedWorkflowCode:
    """Renders a workflow definition, in the shape the read API returns, as SDK source."""
    return _Renderer(definition).render()


# Plain JSON values print as literals. These three wrap what JSON cannot say: a call, a bare
# identifier, and a comment that keeps its place in a list or an object.


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
    escaped = re.sub(r"[\x00-\x1f]", lambda match: f"\\x{ord(match.group(0)):02x}", escaped)
    return f"'{escaped}'"


def _key(key: str) -> str:
    return key if _IDENTIFIER.match(key) else _quote(key)


def _comment_line(indent: str, text: str) -> str:
    # A step name is free text, so a line terminator in it would end the comment and turn the
    # rest of the name into code. U+2028 and U+2029 end a line in JavaScript too.
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
    """The one-line form of a node, or None when the node holds a comment and has to break."""
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
        # A trailing object hugs the parentheses, the way a formatter prints `workflow({ ... })`.
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
    """The action id `emit.ts` derives from a step name."""
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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_set(value: Any) -> bool:
    """Whether a stored field carries a value the editor's defaults do not: `""`, `[]`, `{}`, None and
    whitespace all count as unset, and so does a container that holds nothing but those."""
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
    """One action at one place in the path. `arms` is set on a branch, one path per condition."""

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
        # The steps inside the arms of a branch that is kept as a comment. They are placed
        # nowhere, so they render nothing and warn once each.
        self.dropped: set[str] = set()
        # Which arm of the stored branch each rendered arm came from, after empty arms are dropped.
        self.kept_arms: dict[str, list[int]] = {}
        # The secret variable each step names, so two distinct steps naming one variable warn.
        self.secret_owner: dict[str, str] = {}
        # The step calls by action id, without their `id` option, and the comment blocks of the
        # steps that have no constructor.
        self.calls: dict[str, _Call] = {}
        self.comments: dict[str, _Comment] = {}
        # A step placed more than once prints as one const. `repeats` maps each re-placement to the
        # first placement, `hoisted` lists those first placements in graph order, and
        # `const_names` gives each of them its const.
        self.repeats: dict[str, str] = {}
        self.hoisted: list[str] = []
        self.const_names: dict[str, str] = {}
        self.const_definitions: list[tuple[str, str]] = []

        actions = definition.get("actions")
        self.actions: dict[str, dict[str, Any]] = {}
        for action in actions if isinstance(actions, list) else []:
            if isinstance(action, dict) and isinstance(action.get("id"), str):
                self.actions.setdefault(action["id"], action)
        self.continue_to: dict[str, str] = {}
        self.branch_to: dict[str, dict[int, str]] = {}
        edges = definition.get("edges")
        for edge in edges if isinstance(edges, list) else []:
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
        self.warnings.append(CodeWarning(action_id=action_id, message=message))

    def use(self, name: str) -> str:
        self.imports.add(name)
        return name

    def walk(self, start: str, stop: str) -> tuple[_Placement, ...]:
        """Follows `continue` edges from `start` until `stop`, placing a branch's arms in between.

        An arm stops where the branch's own `continue` edge points, which is the step after the
        branch, so this reads back exactly the path `emit.ts` laid out.
        """
        placements: list[_Placement] = []
        node = start
        while node != stop:
            action = self.actions.get(node)
            if action is None or node == EXIT_ID or node in self.visited:
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
                arms = self.walk_arms(action, EXIT_ID) if action.get("type") == "conditional_branch" else None
                placements.append(_Placement(action=action, arms=arms))
                break
            arms = None
            if action.get("type") == "conditional_branch":
                arms = self.walk_arms(action, following)
            elif self.branch_to.get(node):
                self.warn(
                    node, f'The branch edges out of "{self._name(action)}" are dropped. Only its next step is kept.'
                )
            placements.append(_Placement(action=action, arms=arms))
            node = following
        return tuple(placements)

    def walk_arms(self, action: dict[str, Any], rejoin: str) -> tuple[tuple[_Placement, ...], ...]:
        conditions = (action.get("config") or {}).get("conditions") or []
        targets = self.branch_to.get(action["id"], {})
        arms: list[tuple[_Placement, ...]] = []
        for index, condition in enumerate(conditions):
            target = targets.get(index)
            arm_name = condition.get("name") if isinstance(condition, dict) else None
            if target is None:
                self.warn(
                    action["id"],
                    f'The arm "{arm_name or index}" of "{self._name(action)}" has no edge. Add a step to it before you push.',
                )
                arms.append(())
            else:
                arms.append(self.walk(target, rejoin))
        return tuple(arms)

    @staticmethod
    def _name(action: dict[str, Any]) -> str:
        name = action.get("name")
        return name if isinstance(name, str) and name else action["id"]

    @classmethod
    def _base_options(cls, action: dict[str, Any]) -> dict[str, Any]:
        """The options every step constructor opens with, in the order `emit.ts` writes them."""
        options: dict[str, Any] = {"name": cls._name(action)}
        description = action.get("description")
        if _is_set(description):
            options["description"] = description
        return options

    @staticmethod
    def _flatten(placements: tuple[_Placement, ...]) -> Iterator[_Placement]:
        # The order `emit.ts` hands out ids in: a branch, then its arms, then the step after it.
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
        self.warn_step_settings(action)
        call: _Call | None = None
        if kind == "delay":
            call = self.render_delay(action, config)
        elif kind == "function":
            call = self.render_function(action, config)
        elif kind == "function_email":
            call = self.render_email(action, config)
        elif kind == "conditional_branch":
            call = self.render_branch(action, config, placement.arms or ())
        if call is None:
            self.warn(
                action["id"],
                f'The {kind} step "{self._name(action)}" has no constructor in {PACKAGE}. It is kept in place as a comment.',
            )
            for arm in placement.arms or ():
                for inner in self._flatten(arm):
                    self.dropped.add(inner.id)
                    self.warn(
                        inner.id,
                        f'"{inner.name}" sits inside "{self._name(action)}", which is kept as a comment, so it is dropped.',
                    )
            self.comments[action["id"]] = _Comment(
                (
                    f'The {kind} step "{self._name(action)}" is kept as JSON. Replace it or remove it before you push.',
                    *_json_lines(action),
                )
            )
        else:
            self.calls[action["id"]] = call

    def warn_step_settings(self, action: dict[str, Any]) -> None:
        name = self._name(action)
        filters = action.get("filters")
        if isinstance(filters, dict) and any(
            filters.get(key) for key in ("events", "actions", "properties", "filter_test_accounts")
        ):
            self.warn(
                action["id"],
                f'The conditions that gate "{name}" are dropped. A step cannot carry its own filters in {PACKAGE}.',
            )
        if action.get("on_error") == "abort":
            self.warn(
                action["id"],
                f'"{name}" aborts the run on failure. A step cannot set that in {PACKAGE}, so a push resets it to continue.',
            )
        if action.get("output_variable"):
            self.warn(
                action["id"],
                f'The output variable of "{name}" is dropped. {PACKAGE} cannot declare one, so later steps that read it get nothing.',
            )

    def warn_extra_config(self, action: dict[str, Any], config: dict[str, Any], known: frozenset[str]) -> None:
        for key, value in config.items():
            if key not in known and value not in (None, "", [], {}):
                self.warn(
                    action["id"],
                    f'The setting "{key}" of "{self._name(action)}" is dropped. {PACKAGE} has no field for it.',
                )

    def render_delay(self, action: dict[str, Any], config: dict[str, Any]) -> _Call | None:
        duration = config.get("delay_duration")
        if not isinstance(duration, str) or not duration:
            return None
        match = _DURATION.match(duration)
        if match is None or float(match["amount"]) == 0 or float(match["amount"]) > _DURATION_CAPS[match["unit"]]:
            self.warn(
                action["id"],
                f'"{self._name(action)}" waits for "{duration}", which {PACKAGE} refuses at push. Write a positive amount up to 60s, 60m, 24h or 30d.',
            )
        self.warn_extra_config(action, config, frozenset({"delay_duration"}))
        return _Call(self.use("delay"), (duration, self._base_options(action)))

    def secret_base(self, action: dict[str, Any]) -> str:
        """The id a secret's variable is named after.

        A step placed twice shares one `secret()` in the source, so the numbered re-placement
        names the variable after the first placement. Without that the two placements would
        render differently and never fold back into one const.
        """
        match = _REPEAT_ID.match(action["id"])
        if match and match["count"] == str(int(match["count"])):
            first = self.actions.get(match["base"])
            if (
                first is not None
                and first.get("type") == action.get("type")
                and first.get("config") == action.get("config")
            ):
                return match["base"]
        return action["id"]

    def render_inputs(self, action: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, raw in inputs.items():
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
            elif isinstance(raw, dict) and set(raw) <= _DERIVED_INPUT_KEYS | {"value"}:
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
        """`webhook()` when every input is one it writes, else None so `fn()` keeps the exact inputs."""
        if set(values) - _WEBHOOK_INPUTS or not isinstance(values.get("url"), str):
            return None
        method = values.get("method", "POST")
        body = values.get("body", {})
        headers = values.get("headers", {})
        signing_secret = values.get("signing_secret")
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
        # The editor stores `cc`, `bcc` and `replyTo` empty on every email, so only a value is a loss.
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
        if operator not in _OPERATORS:
            self.warn(
                action_id,
                f'The operator "{operator}" on "{key}" is not one {PACKAGE} declares. The file will not type-check until you change it.',
            )
        for extra in condition:
            if extra not in ("key", "operator", "type", "value"):
                self.warn(
                    action_id,
                    f'The field "{extra}" of the condition on "{key}" is dropped. {PACKAGE} has no field for it.',
                )
        args: tuple[Any, ...] = (key, operator)
        if condition.get("value") is not None:
            if not isinstance(condition["value"], list):
                self.warn(
                    action_id,
                    f'The condition on "{key}" compares against a single value. {PACKAGE} takes a list, so the file will not type-check until you wrap it in [].',
                )
            args = (*args, condition["value"])
        return _Call(self.use(constructor), args)

    def render_branch(
        self, action: dict[str, Any], config: dict[str, Any], placed_arms: tuple[tuple[_Placement, ...], ...]
    ) -> _Call | None:
        conditions = config.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            return None
        self.warn_extra_config(action, config, frozenset({"conditions"}))
        arms = []
        kept: list[int] = []
        for index, condition in enumerate(conditions):
            if not isinstance(condition, dict):
                return None
            # An empty arm sends a person to the step after the branch, which is where the
            # fall-through goes too, so dropping it changes nothing at run time. `emit.ts`
            # refuses an empty arm, so keeping it would produce a file that never pushes.
            if index >= len(placed_arms) or not placed_arms[index]:
                self.warn(
                    action["id"],
                    f'The arm "{condition.get("name", index)}" of "{self._name(action)}" has no steps, so it is dropped. A person who matches it continues after the branch either way.',
                )
                continue
            filters = _dict(condition.get("filters"))
            properties = filters.get("properties")
            if not isinstance(properties, list) or not properties:
                return None
            if any(filters.get(key) for key in filters if key not in _DERIVED_FILTER_KEYS and key != "properties"):
                return None
            when = [self.render_condition(action["id"], entry) for entry in properties]
            if any(entry is None for entry in when):
                return None
            # `then` is filled once every arm's steps are rendered, because a step inside an arm
            # may be a re-placement of a step that comes earlier in the path.
            arms.append({"name": condition.get("name", ""), "when": when, "then": None})
            kept.append(index)
        if not arms:
            return None
        self.kept_arms[action["id"]] = kept
        return _Call(self.use("branch"), ({**self._base_options(action), "branches": arms},))

    def hoist_repeats(self, placements: tuple[_Placement, ...]) -> None:
        """Turns a step placed more than once into one const, following the `_2` rule of `emit.ts`.

        A placement is a repeat when its id is an earlier placement's id with `_<n>` appended,
        `n` is one more than the placements that base already has, and the two steps render the
        same. Anything else is its own step, with the id it carries.
        """
        count_of_base: dict[str, int] = {}
        for placement in placements:
            action_id = placement.id
            call = self.calls.get(action_id)
            if call is None or placement.action.get("type") not in _HOISTABLE_TYPES:
                continue
            match = _REPEAT_ID.match(action_id)
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
        # `emit.ts` derives the id from the name, so the id is written only when it differs.
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
            for index, spec in zip(self.kept_arms[action_id], call.args[-1]["branches"]):
                spec["then"] = _Call(self.use("path"), tuple(self.node_for(entry) for entry in placement.arms[index]))
        return self.with_id(call, placement.action)

    def render_trigger(self, trigger: dict[str, Any] | None) -> Any:
        if trigger is None:
            self.warn(TRIGGER_ID, "The workflow has no trigger step. Add `on` before you push.")
            return _Comment(("Add the trigger here: on: onEvent({ event: '...' }) or on: onSchedule().",))
        config = _dict(trigger.get("config"))
        kind = config.get("type")
        if kind == "schedule":
            return _Call(self.use("onSchedule"), ())
        filters = _dict(config.get("filters"))
        events = [event for event in filters.get("events") or [] if isinstance(event, dict)]
        if kind == "event" and events and events[0].get("type") == "events" and isinstance(events[0].get("id"), str):
            first = events[0]
            if len(events) > 1:
                self.warn(
                    TRIGGER_ID, f"Only the first of the {len(events)} trigger events is kept. onEvent takes one event."
                )
            if filters.get("actions"):
                self.warn(TRIGGER_ID, "The actions in the trigger are dropped. onEvent takes an event name.")
            if filters.get("properties"):
                self.warn(
                    TRIGGER_ID,
                    "The trigger conditions that apply to every event are dropped. onEvent takes conditions on the event only.",
                )
            if filters.get("filter_test_accounts"):
                self.warn(
                    TRIGGER_ID,
                    f"The trigger filters out test accounts. {PACKAGE} cannot set that, so a push turns it off.",
                )
            options: dict[str, Any] = {"event": first["id"]}
            properties = []
            for entry in first.get("properties") or []:
                condition = self.render_condition(TRIGGER_ID, entry)
                if condition is None:
                    self.warn(
                        TRIGGER_ID,
                        f"A condition on the trigger event is dropped. {PACKAGE} reads person, event and group properties only.",
                    )
                else:
                    properties.append(condition)
            if properties:
                options["properties"] = properties
            return _Call(self.use("onEvent"), (options,))
        self.warn(
            TRIGGER_ID, f'The trigger type "{kind}" has no constructor in {PACKAGE}. Add `on` by hand before you push.'
        )
        return _Comment(
            ("The trigger is kept as JSON. Replace it with onEvent(...) or onSchedule():", *_json_lines(config))
        )

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
            rendered.append({"key": key, "type": variable["type"], "default": variable.get("default", "")})
        return rendered

    def render(self) -> RenderedWorkflowCode:
        definition = self.definition
        stored_name = definition.get("name")
        name = stored_name if isinstance(stored_name, str) else ""
        stored_key = definition.get("key")
        key = stored_key if isinstance(stored_key, str) and stored_key else _kebab(name)

        start = self.continue_to.get(TRIGGER_ID)
        if start is None:
            self.warn(TRIGGER_ID, "The trigger leads to no step. The workflow has no steps.")
            placements: tuple[_Placement, ...] = ()
        else:
            placements = self.walk(start, EXIT_ID)
        for action_id, action in self.actions.items():
            if action_id not in self.visited and action_id not in (TRIGGER_ID, EXIT_ID):
                self.warn(action_id, f'"{self._name(action)}" is not reached from the trigger and is dropped.')

        on = self.render_trigger(self.actions.get(TRIGGER_ID))
        flat = tuple(self._flatten(placements))
        for placement in flat:
            self.render_step(placement)
        self.hoist_repeats(flat)

        options: dict[str, Any] = {"key": key, "name": name}
        if definition.get("description"):
            options["description"] = definition["description"]
        options["status"] = definition.get("status") or "draft"
        exit_condition = definition.get("exit_condition") or _DEFAULT_EXIT_CONDITION
        if exit_condition not in _SDK_EXIT_CONDITIONS:
            self.warn(
                EXIT_ID,
                f'The exit condition "{exit_condition}" needs a conversion goal, which {PACKAGE} cannot declare. The workflow exits only at the end.',
            )
        elif exit_condition != _DEFAULT_EXIT_CONDITION:
            options["exitCondition"] = exit_condition
        variables = self.render_variables()
        if variables:
            options["variables"] = variables
        # The editor stores `{window_minutes: null, filters: []}` on a new workflow, which is no goal.
        conversion = _dict(definition.get("conversion"))
        if _is_set(conversion.get("filters")) or _is_set(conversion.get("events")):
            self.warn(None, f"The conversion goal is dropped. {PACKAGE} cannot declare one.")
        if definition.get("trigger_masking"):
            self.warn(TRIGGER_ID, f"The trigger masking is dropped. {PACKAGE} cannot declare it.")
        options["on"] = on

        exit_action = self.actions.get(EXIT_ID)
        reason = ((exit_action or {}).get("config") or {}).get("reason")
        if exit_action is None:
            self.warn(EXIT_ID, "The workflow has no exit step. The exit reason is left empty.")

        export_name = _camel(key, "workflow")
        self.use("workflow")
        self.use("path")
        if export_name in self.imports:
            export_name += "Workflow"
        self.name_consts({*self.imports, export_name})
        options["steps"] = _Call("path", tuple(self.node_for(placement) for placement in placements))
        options["exit"] = {"reason": reason if isinstance(reason, str) else ""}

        header = []
        if self.warnings:
            header.append(f"// {PACKAGE} cannot express everything in this workflow. Review these before you push:")
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
