"""A Resend automation, as `GET /automations/{id}` returns it, turned into a draft PostHog workflow.

Steps that have no PostHog equivalent are bridged over and named in the notes, so the team can review the draft before
enabling it. Nothing about people is read, and a contact is never updated or deleted.
"""

import re
from collections.abc import Mapping
from typing import Any

from products.workflows.backend.facade.contracts import ImportedEmail, ImportNote, TranslatedWorkflow
from products.workflows.backend.facade.enums import WorkflowImportNoteLevel as NoteLevel
from products.workflows.backend.services.customerio_import.translator import (
    _EXIT_ID,
    _MAX_WAIT_SECONDS,
    TRIGGER_ID,
    _duration,
    _empty_trigger,
    _exit_action,
    _prune_unreachable,
)

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(second|sec|minute|min|hour|hr|day|week)s?\b", re.IGNORECASE)
_UNIT_SECONDS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400, "week": 604800}
_DEFAULT_WAIT_SECONDS = 86400
_UNFILLED_VARIABLE = re.compile(r"\bvariables\.([\w-]+)")
_OPERATORS = {
    "eq": "exact",
    "neq": "is_not",
    "gt": "gt",
    "gte": "gte",
    "lt": "lt",
    "lte": "lte",
    "contains": "icontains",
    "exists": "is_set",
    "is_empty": "is_not_set",
}
_UNARY = {"is_set", "is_not_set"}
_SKIPPED_STEPS = {
    "add_to_segment": "PostHog has no segments to add people to, so this step was left out. Use a cohort instead.",
    "contact_update": "PostHog doesn't update people from here, so this step was left out. Add an update person "
    "properties step if you need it.",
    "contact_delete": "PostHog doesn't delete people from a workflow, so this step was left out.",
}


def translate_automation(automation: dict[str, Any], emails: Mapping[str, ImportedEmail | None]) -> TranslatedWorkflow:
    """`emails` holds each template the automation sends, by the id or alias its steps name, or None if unreadable."""
    return _Builder(automation, emails).build()


class _Builder:
    def __init__(self, automation: dict[str, Any], emails: Mapping[str, ImportedEmail | None]) -> None:
        self.automation = automation
        self.emails = emails
        self.notes: list[ImportNote] = []
        self.steps = {
            str(step["key"]): step
            for step in automation.get("steps") or []
            if isinstance(step, dict) and step.get("key") is not None
        }
        self.links: dict[str, list[tuple[str, str]]] = {}
        for connection in automation.get("connections") or []:
            if isinstance(connection, dict):
                self.links.setdefault(str(connection.get("from")), []).append(
                    (str(connection.get("to")), str(connection.get("type") or "default"))
                )

    def note(self, level: NoteLevel, message: str, step_key: str | None = None) -> None:
        self.notes.append(ImportNote(level=level, message=message, step_id=step_key, step_name=step_key))

    def build(self) -> TranslatedWorkflow:
        name = str(self.automation.get("name") or "Imported from Resend")[:400]
        trigger_key = next((key for key, step in self.steps.items() if step.get("type") == "trigger"), None)
        trigger = self._trigger(trigger_key)
        actions: list[dict[str, Any]] = [
            {"id": TRIGGER_ID, "name": "Trigger", "description": "", "type": "trigger", "config": trigger}
        ]
        for key, step in self.steps.items():
            if key == trigger_key:
                continue
            translated = self._action(key, step)
            if translated is not None:
                actions.append(translated)
        edges = self._edges(trigger_key, {action["id"] for action in actions})
        if any(edge["to"] == _EXIT_ID for edge in edges):
            actions.append(_exit_action(_EXIT_ID, "Exit"))
        graph = _prune_unreachable(actions, edges)
        if self.automation.get("status") == "enabled":
            self.note(
                NoteLevel.APPROXIMATED,
                "This automation is on in Resend. Turn it off there when you enable this workflow, or people get "
                "both emails.",
            )
        kept = {action["id"] for action in graph.actions}
        return TranslatedWorkflow(
            source_id=str(self.automation.get("id")),
            name=name,
            workflow={
                "name": name,
                "description": f"Imported from Resend automation {self.automation.get('id')}.",
                "trigger": trigger,
                "actions": graph.actions,
                "edges": graph.edges,
                "exit_condition": "exit_only_at_end",
            },
            notes=tuple(note for note in self.notes if note.step_id is None or note.step_id in kept),
        )

    def _trigger(self, key: str | None) -> dict[str, Any]:
        event_name = (self.steps[key].get("config") or {}).get("event_name") if key else None
        if not event_name:
            self.note(NoteLevel.NEEDS_INPUT, "Pick the event that starts this workflow.")
            return _empty_trigger()
        self.note(
            NoteLevel.NEEDS_INPUT,
            f"Your app sends {event_name} to Resend. Send it to PostHog too, or this workflow never starts.",
        )
        event = {"id": event_name, "name": event_name, "type": "events", "order": 0}
        return {"type": "event", "filters": {"events": [event]}}

    def _action(self, key: str, step: dict[str, Any]) -> dict[str, Any] | None:
        step_type = str(step.get("type"))
        config = step.get("config") or {}
        base: dict[str, Any] = {"id": key, "name": _step_name(key, step_type), "description": ""}
        match step_type:
            case "send_email":
                return self._email(key, config, base)
            case "delay":
                return {**base, "type": "delay", "config": {"delay_duration": self._duration(key, config, "duration")}}
            case "condition":
                return {**base, "type": "conditional_branch", "config": {"conditions": self._conditions(key, config)}}
            case "wait_for_event":
                return self._wait(key, config, base)
            case _:
                message = _SKIPPED_STEPS.get(step_type, f"PostHog has no {step_type} step, so this was left out.")
                self.note(NoteLevel.UNSUPPORTED, f"{_step_name(key, step_type)}: {message}")
                return None

    def _duration(self, key: str, config: dict[str, Any], field: str, *, cap: int | None = None) -> str:
        text = str(config.get(field) or "")
        seconds = sum(float(amount) * _UNIT_SECONDS[unit.lower()] for amount, unit in _DURATION_PART.findall(text))
        if seconds <= 0:
            self.note(
                NoteLevel.NEEDS_INPUT,
                f'PostHog couldn\'t read the time "{text}", so it used 1 day. Set the time you want.',
                key,
            )
            seconds = _DEFAULT_WAIT_SECONDS
        if cap is not None and seconds > cap:
            self.note(NoteLevel.APPROXIMATED, f"Waits are capped at {_duration(cap)}.", key)
            seconds = cap
        return _duration(int(seconds))

    def _email(self, key: str, config: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        reference = (config.get("template") or {}).get("id")
        imported = self.emails.get(str(reference)) if reference else None
        value: dict[str, Any] = {
            "to": {"email": "{{ person.properties.email }}", "name": ""},
            "from": {"email": "", "name": ""},
            "replyTo": "",
            "preheader": "",
            "subject": "",
            "html": "",
        }
        if imported is None:
            self.note(NoteLevel.NEEDS_INPUT, "PostHog couldn't read this email's template. Add its content.", key)
            value.update(subject=str(config.get("subject") or base["name"]), html="<p>Add this email's content.</p>")
        else:
            variables = (config.get("template") or {}).get("variables") or {}
            value.update(
                subject=self._with_variables(key, imported.subject, variables),
                html=self._with_variables(key, imported.html, variables),
                replyTo=imported.reply_to,
                **{"from": _sender(imported)},
            )
            if imported.text:
                value["text"] = self._with_variables(key, imported.text, variables)
            for note in imported.notes:
                self.note(NoteLevel.NEEDS_INPUT, note, key)
            unfilled = sorted(set(_UNFILLED_VARIABLE.findall(f"{value['subject']} {value['html']}")))
            if unfilled:
                self.note(
                    NoteLevel.NEEDS_INPUT,
                    f"Nothing fills {', '.join(unfilled)} here, so it prints blank or its default. Replace it with a "
                    "person or event property.",
                    key,
                )
        if config.get("subject"):
            value["subject"] = str(config["subject"])
        if config.get("reply_to"):
            value["replyTo"] = str(config["reply_to"])
        if config.get("from"):
            self.note(NoteLevel.NEEDS_INPUT, f"This step sends from {config['from']}. Choose that sender here.", key)
        return {
            **base,
            "type": "function_email",
            "config": {"template_id": "template-email", "inputs": {"email": {"templating": "liquid", "value": value}}},
        }

    def _with_variables(self, key: str, text: str, variables: Mapping[str, Any]) -> str:
        for name, source in variables.items():
            replacement = self._variable_source(key, name, source)
            text = re.sub(rf"\bvariables\.{re.escape(name)}\b", replacement, text)
        return text

    def _variable_source(self, key: str, name: str, source: Any) -> str:
        reference = source.get("var") if isinstance(source, dict) else None
        if reference is None:
            return '"' + str(source).replace('"', "") + '"'
        path = str(reference)
        if path.startswith("event."):
            return f"event.properties.{path.removeprefix('event.')}"
        if path.startswith("contact."):
            return f"person.properties.{path.removeprefix('contact.')}"
        self.note(
            NoteLevel.NEEDS_INPUT, f"{name} reads {path}, which PostHog doesn't have. Set where it comes from.", key
        )
        return f"variables.{name}"

    def _conditions(self, key: str, config: dict[str, Any]) -> list[dict[str, Any]]:
        groups = self._condition_groups(key, config)
        if not groups:
            self.note(NoteLevel.NEEDS_INPUT, "PostHog couldn't read this condition. Set what it checks.", key)
            return [{"filters": {"properties": []}, "name": "Condition 1"}]
        return [
            {"filters": {"properties": properties}, "name": f"Condition {index + 1}"}
            for index, properties in enumerate(groups)
        ]

    def _condition_groups(self, key: str, config: dict[str, Any]) -> list[list[dict[str, Any]]]:
        kind = config.get("type")
        if kind == "rule":
            prop = self._property(key, config)
            return [[prop]] if prop else []
        rules = [rule for rule in config.get("rules") or [] if isinstance(rule, dict)]
        if kind == "or":
            return [group for rule in rules for group in self._condition_groups(key, rule)]
        if kind == "and":
            combined: list[dict[str, Any]] = []
            for rule in rules:
                groups = self._condition_groups(key, rule)
                if len(groups) > 1:
                    self.note(
                        NoteLevel.NEEDS_INPUT, 'An "or" inside an "and" can\'t be kept. Check this condition.', key
                    )
                combined.extend(groups[0] if groups else [])
            return [combined] if combined else []
        return []

    def _property(self, key: str, rule: dict[str, Any]) -> dict[str, Any] | None:
        field = str(rule.get("field") or "")
        operator = str(rule.get("operator") or "")
        namespace, _, name = field.partition(".")
        property_type = {"contact": "person", "event": "event"}.get(namespace)
        value = rule.get("value")
        if property_type is None or not name or isinstance(value, dict):
            self.note(NoteLevel.NEEDS_INPUT, f"PostHog can't check {field}. Set what this condition checks.", key)
            return None
        if operator == "starts_with":
            return {"key": name, "operator": "regex", "type": property_type, "value": f"^{re.escape(str(value))}"}
        if operator == "ends_with":
            return {"key": name, "operator": "regex", "type": property_type, "value": f"{re.escape(str(value))}$"}
        mapped = _OPERATORS.get(operator)
        if mapped is None:
            self.note(NoteLevel.NEEDS_INPUT, f"PostHog can't use the check {operator}. Set this condition.", key)
            return None
        result: dict[str, Any] = {"key": name, "operator": mapped, "type": property_type}
        if mapped not in _UNARY:
            result["value"] = value
        return result

    def _wait(self, key: str, config: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        event_name = config.get("event_name")
        if config.get("filter_rule"):
            self.note(NoteLevel.NEEDS_INPUT, "Resend filters which events end this wait. Add that filter here.", key)
        if not config.get("timeout"):
            self.note(NoteLevel.APPROXIMATED, "Resend sets no time limit here. PostHog waits at most 30 days.", key)
            timeout = _duration(_MAX_WAIT_SECONDS)
        else:
            timeout = self._duration(key, config, "timeout", cap=_MAX_WAIT_SECONDS)
        events = []
        if event_name:
            event = {"id": event_name, "name": event_name, "type": "events", "order": 0, "properties": []}
            events = [{"name": event_name, "filters": {"events": [event]}}]
            self.note(NoteLevel.NEEDS_INPUT, f"Send {event_name} to PostHog too, or this step always times out.", key)
        return {
            **base,
            "type": "wait_until_condition",
            "config": {"condition": {"filters": None}, "events": events, "max_wait_duration": timeout},
        }

    def _next_kept(self, target: str, actions: set[str], seen: set[str] | None = None) -> str:
        """The step a link reaches once skipped steps are bridged over."""
        seen = seen or set()
        if target in actions:
            return target
        if target in seen or target not in self.steps:
            return _EXIT_ID
        seen.add(target)
        following = self.links.get(target, [])
        return self._next_kept(following[0][0], actions, seen) if following else _EXIT_ID

    def _edges(self, trigger_key: str | None, actions: set[str]) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        if trigger_key is not None:
            first = self.links.get(trigger_key, [])
            target = self._next_kept(first[0][0], actions) if first else _EXIT_ID
            edges.append({"from": TRIGGER_ID, "to": target, "type": "continue"})
        else:
            edges.append({"from": TRIGGER_ID, "to": _EXIT_ID, "type": "continue"})
        for key, step in self.steps.items():
            if key not in actions:
                continue
            step_type = step.get("type")
            links = self.links.get(key, [])
            if step_type == "condition":
                groups = len(self._condition_groups_quiet(key))
                edges.extend(self._branch_edges(key, links, "condition_met", "condition_not_met", actions, groups))
            elif step_type == "wait_for_event":
                edges.extend(self._branch_edges(key, links, "event_received", "timeout", actions, 1))
            else:
                target = self._next_kept(links[0][0], actions) if links else _EXIT_ID
                edges.append({"from": key, "to": target, "type": "continue"})
        return edges

    def _branch_edges(
        self,
        key: str,
        links: list[tuple[str, str]],
        match_type: str,
        other_type: str,
        actions: set[str],
        branches: int,
    ) -> list[dict[str, Any]]:
        match_target = next((to for to, link_type in links if link_type == match_type), None)
        other_target = next((to for to, link_type in links if link_type == other_type), None)
        matched = self._next_kept(match_target, actions) if match_target else _EXIT_ID
        other = self._next_kept(other_target, actions) if other_target else _EXIT_ID
        # A condition with "or" rules becomes several conditions, and PostHog gives each one its own path.
        return [
            *({"from": key, "to": matched, "type": "branch", "index": index} for index in range(max(branches, 1))),
            {"from": key, "to": other, "type": "continue"},
        ]

    def _condition_groups_quiet(self, key: str) -> list[list[dict[str, Any]]]:
        # Reading the groups again to count them must not repeat the notes the first read wrote.
        kept = list(self.notes)
        groups = self._condition_groups(key, self.steps[key].get("config") or {})
        self.notes = kept
        return groups


def _step_name(key: str, step_type: str) -> str:
    return f"{step_type.replace('_', ' ').capitalize()} ({key})"[:400]


def _sender(email: ImportedEmail) -> dict[str, Any]:
    if email.sender_integration_id is not None:
        return {"integrationId": email.sender_integration_id, "email": email.from_email, "name": email.from_name}
    return {"email": email.from_email, "name": email.from_name}
