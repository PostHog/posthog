"""A Resend automation, as `GET /automations/{id}` returns it, turned into a draft PostHog workflow.

Every Resend step becomes the PostHog step that does the same thing. What can't carry over is named in the notes, so
the team can review the draft before enabling it. A step type PostHog doesn't know is bridged over, and a contact delete
ends its path, because PostHog has no step that deletes a person.
"""

import re
import json
from collections.abc import Mapping
from dataclasses import field as dataclass_field
from itertools import islice
from typing import Any

from posthog.hogql.escape_sql import escape_hogql_identifier

from posthog.dataclasses import frozen

from products.workflows.backend.facade.contracts import ImportedEmail, ImportedStepEmail, ImportNote, TranslatedWorkflow
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
# The email renderer treats these differently inside a quoted value from how Resend prints them.
_UNSAFE_IN_LITERAL = re.compile(r"\\|\{\{|\}\}|\{%|%\}|&(?:\w+|#\d+|#[xX][0-9a-fA-F]+);")
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
_COMPARISONS = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_NUMERIC_COMPARISONS = {"gt", "gte", "lt", "lte"}
# Resend keeps these on the contact itself, and they don't match a PostHog person property of the same name.
_CONTACT_ONLY_FIELDS = {"id", "unsubscribed", "created_at"}
_CONTACT_VARIABLE_PROPERTIES = {"FIRST_NAME": "first_name", "LAST_NAME": "last_name", "EMAIL": "email"}
# An "or" inside an "and" multiplies paths, and past this the editor can't show the step usefully.
_MAX_CONDITION_PATHS = 20
_HOG_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
ADD_TO_STATIC_COHORT_TEMPLATE_ID = "template-posthog-add-to-static-cohort"
OPT_OUT_OF_MESSAGES_TEMPLATE_ID = "template-posthog-opt-out-of-messages"


@frozen
class SegmentCohort:
    """The static cohort that stands in for a Resend segment, or why there is none."""

    name: str = ""
    cohort_id: int | None = None
    problem: str = ""


@frozen
class TranslationContext:
    step_emails: Mapping[str, ImportedStepEmail] = dataclass_field(default_factory=dict)
    segment_cohorts: Mapping[str, SegmentCohort] = dataclass_field(default_factory=dict)
    can_opt_out: bool = False
    # Pre-release steps this team can't enable yet.
    unavailable_templates: frozenset[str] = frozenset()


def translate_automation(
    automation: dict[str, Any],
    emails: Mapping[str, ImportedEmail | None],
    context: TranslationContext | None = None,
) -> TranslatedWorkflow:
    """`emails` holds each template the automation sends, by the id or alias its steps name, or None if unreadable."""
    return _Builder(automation, emails, context or TranslationContext()).build()


class _Builder:
    def __init__(
        self,
        automation: dict[str, Any],
        emails: Mapping[str, ImportedEmail | None],
        context: TranslationContext,
    ) -> None:
        self.automation = automation
        self.emails = emails
        self.context = context
        self.notes: list[ImportNote] = []
        self.condition_paths: dict[str, int] = {}
        # A contact update that also unsubscribes becomes two steps, and this names the second one.
        self.second_steps: dict[str, str] = {}
        steps = {
            str(step["key"]): step
            for step in automation.get("steps") or []
            if isinstance(step, dict) and step.get("key") is not None
        }
        # A source key may equal an id this translator adds, and a graph can't hold the same id twice.
        renamed = _rename_reserved_keys(steps)
        self.steps = {renamed.get(key, key): step for key, step in steps.items()}
        self.links: dict[str, list[tuple[str, str]]] = {}
        for connection in automation.get("connections") or []:
            if isinstance(connection, dict):
                source, target = str(connection.get("from")), str(connection.get("to"))
                self.links.setdefault(renamed.get(source, source), []).append(
                    (renamed.get(target, target), str(connection.get("type") or "default"))
                )

    def note(self, level: NoteLevel, message: str, step_key: str | None = None) -> None:
        note = ImportNote(level=level, message=message, step_id=step_key, step_name=step_key)
        # An email's subject, HTML and text each read the same variables.
        if note not in self.notes:
            self.notes.append(note)

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
            actions.extend(self._actions(key, step))
        edges = self._edges(trigger_key, {action["id"] for action in actions})
        if any(edge["to"] == _EXIT_ID for edge in edges):
            actions.append(_exit_action(_EXIT_ID, "Exit"))
        graph = _prune_unreachable(actions, edges)
        reachable = {action["id"] for action in graph.actions}
        for action in actions:
            if action["id"] not in reachable:
                self.note(NoteLevel.UNSUPPORTED, f"No path reaches {action['name']}, so it was left out.")
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
        if any(step.get("type") == "send_email" for step in self.steps.values()):
            self.note(
                NoteLevel.APPROXIMATED,
                "Resend finds the contact from the event. PostHog sends to the email property of the event's person, "
                "so make sure each person has one.",
            )
        event = {"id": event_name, "name": event_name, "type": "events", "order": 0}
        return {"type": "event", "filters": {"events": [event]}}

    def _actions(self, key: str, step: dict[str, Any]) -> list[dict[str, Any]]:
        step_type = str(step.get("type"))
        config = step.get("config") or {}
        base: dict[str, Any] = {"id": key, "name": _step_name(key, step_type), "description": ""}
        match step_type:
            case "send_email":
                return [self._email(key, str(step.get("key")), config, base)]
            case "delay":
                return [
                    {**base, "type": "delay", "config": {"delay_duration": self._duration(key, config, "duration")}}
                ]
            case "condition":
                return [{**base, "type": "conditional_branch", "config": {"conditions": self._conditions(key, config)}}]
            case "wait_for_event":
                return [self._wait(key, config, base)]
            case "contact_update":
                return self._contact_update(key, config, base)
            case "add_to_segment":
                return [self._add_to_segment(key, config, base)]
            case "contact_delete":
                return [self._contact_delete(key, base)]
            case "trigger":
                self.note(
                    NoteLevel.UNSUPPORTED,
                    f"{base['name']}: a PostHog workflow has one trigger, so this one was left out.",
                )
                return []
            case _:
                extra_paths = " Only its first path was kept." if len(self.links.get(key, [])) > 1 else ""
                self.note(
                    NoteLevel.UNSUPPORTED,
                    f"{base['name']}: PostHog has no {step_type} step, so this was left out.{extra_paths}",
                )
                return []

    def _contact_update(self, key: str, config: dict[str, Any], base: dict[str, Any]) -> list[dict[str, Any]]:
        properties: dict[str, Any] = {}
        sources = {name: config[name] for name in ("first_name", "last_name") if name in config}
        custom = config.get("properties")
        sources.update(custom if isinstance(custom, dict) else {})
        for name, source in sources.items():
            value = self._person_value(key, str(name), source)
            if value is not None:
                properties[str(name)] = value
        opt_out = self._opt_out(key, config, base)
        if opt_out is not None and not properties:
            return [opt_out]
        if not properties:
            self.note(NoteLevel.NEEDS_INPUT, "Set the person properties this step updates.", key)
        update = {
            **base,
            "type": "function",
            "config": {
                "template_id": "template-posthog-update-person-properties",
                "inputs": {
                    "distinct_id": {"value": "{event.distinct_id}", "templating": "hog"},
                    "set_properties": {"value": properties, "templating": "hog"},
                },
            },
        }
        if opt_out is None:
            return [update]
        second_id = f"{key}_opt_out"
        while second_id in self.steps:
            second_id += "_"
        self.second_steps[key] = second_id
        return [update, {**opt_out, "id": second_id}]

    def _person_value(self, key: str, name: str, source: Any) -> Any:
        """The value for one property, as a hog template so a number stays a number. None leaves the property out."""
        if isinstance(source, bool | int | float):
            return source
        if isinstance(source, str):
            return source.replace("\\", "\\\\").replace("{", "\\{")
        if isinstance(source, dict) and source.get("var") is not None:
            path = self._readable_path(key, name, str(source["var"]))
            if path is None:
                return None
            self.note(
                NoteLevel.APPROXIMATED,
                "If a variable in this step has no value, PostHog sets that property to empty.",
                key,
            )
            return f"{{{_hog_path(path)}}}"
        self.note(
            NoteLevel.NEEDS_INPUT, f"PostHog can't set {name} to this value, so it was left out. Add it again.", key
        )
        return None

    def _opt_out(self, key: str, config: dict[str, Any], base: dict[str, Any]) -> dict[str, Any] | None:
        unsubscribed = config.get("unsubscribed")
        if unsubscribed is None:
            return None
        if unsubscribed is False:
            self.note(
                NoteLevel.UNSUPPORTED,
                "This step resubscribes the contact. PostHog has no step for that, so it was left out. Remove the "
                "person from your opt-outs if you need to.",
                key,
            )
            return None
        if unsubscribed is not True:
            self.note(
                NoteLevel.NEEDS_INPUT,
                "Resend reads whether to unsubscribe the contact from a variable, and PostHog's opt-out step can't. "
                "Add a condition and an opt out of messages step.",
                key,
            )
            return None
        if not self.context.can_opt_out:
            self.note(
                NoteLevel.NEEDS_INPUT,
                "This step unsubscribes the contact, and changing the opt-out list needs edit access to all "
                "workflows. Ask someone who has it to add an opt out of messages step.",
                key,
            )
            return None
        self._note_if_unavailable(OPT_OUT_OF_MESSAGES_TEMPLATE_ID, "Opt out of messages", key)
        return {
            **base,
            "name": f"Opt out of messages ({key})"[:400],
            "type": "function",
            # A failed opt-out must not continue to a message step.
            "on_error": "abort",
            "config": {
                "template_id": OPT_OUT_OF_MESSAGES_TEMPLATE_ID,
                "inputs": {
                    "category_id": {"value": "$all"},
                    # Liquid inputs come out HTML-escaped, which would turn `a&b@` into `a&amp;b@` and opt out the wrong address.
                    "identifier": {"value": "{person.properties.email}", "templating": "hog"},
                },
            },
        }

    def _add_to_segment(self, key: str, config: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        cohort = self.context.segment_cohorts.get(str(config.get("segment_id")))
        inputs: dict[str, Any] = {}
        if cohort is not None and cohort.cohort_id is not None:
            inputs["cohort_id"] = {"value": cohort.cohort_id}
            self.note(
                NoteLevel.APPROXIMATED,
                f'This step adds people to the static cohort "{cohort.name}", which stands in for the Resend segment. '
                "PostHog doesn't copy who is already in the segment.",
                key,
            )
        else:
            problem = cohort.problem if cohort is not None else "PostHog couldn't read this segment."
            self.note(NoteLevel.NEEDS_INPUT, f"{problem} Choose a static cohort.", key)
        self._note_if_unavailable(ADD_TO_STATIC_COHORT_TEMPLATE_ID, "Add to static cohort", key)
        return {
            **base,
            "type": "function",
            "config": {"template_id": ADD_TO_STATIC_COHORT_TEMPLATE_ID, "inputs": inputs},
        }

    def _contact_delete(self, key: str, base: dict[str, Any]) -> dict[str, Any]:
        self.note(
            NoteLevel.UNSUPPORTED,
            "PostHog has no step that deletes a person, so this path ends here and the person stays in PostHog. "
            "Delete them on the Persons page if you need to.",
            key,
        )
        return {
            **base,
            "name": f"Exit: Resend deletes the contact here ({key})"[:400],
            "description": "Resend deletes the contact at this step. PostHog keeps the person.",
            "type": "exit",
            "config": {"reason": "Resend deletes the contact at this step."},
        }

    def _note_if_unavailable(self, template_id: str, step_name: str, key: str) -> None:
        if template_id in self.context.unavailable_templates:
            self.note(
                NoteLevel.NEEDS_INPUT,
                f"The {step_name} step isn't on for this project yet, so this workflow can't be enabled until it is. "
                "Contact support to turn it on.",
                key,
            )

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
            self.note(
                NoteLevel.APPROXIMATED, f"PostHog waits at most {_duration(cap)}, so this time was shortened.", key
            )
            seconds = cap
        return _duration(int(seconds))

    def _email(self, key: str, source_key: str, config: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        reference = (config.get("template") or {}).get("id")
        imported = self.emails.get(str(reference)) if reference else None
        override = self.context.step_emails.get(source_key) or ImportedStepEmail()
        variables = (config.get("template") or {}).get("variables") or {}
        contact_variables = (*(imported.contact_variables if imported else ()), *override.contact_variables)
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
            value.update(subject=base["name"], html="<p>Add this email's content.</p>")
        else:
            value.update(
                subject=imported.subject,
                html=imported.html,
                replyTo=imported.reply_to,
                **{"from": _sender(imported.from_email, imported.from_name, imported.sender_integration_id)},
            )
            if imported.text:
                value["text"] = imported.text
            for note in imported.notes:
                self.note(NoteLevel.NEEDS_INPUT, note, key)
        if override.subject:
            value["subject"] = override.subject
        for field_name in ("subject", "html", "text"):
            if field_name in value:
                value[field_name] = self._with_variables(key, value[field_name], variables, contact_variables)
        reply_to = config.get("reply_to")
        if reply_to:
            value["replyTo"] = _literal_liquid(
                ", ".join(str(item) for item in reply_to) if isinstance(reply_to, list) else str(reply_to)
            )
        if override.from_email:
            value["from"] = _sender(override.from_email, override.from_name, override.sender_integration_id)
        for note in override.notes:
            self.note(NoteLevel.NEEDS_INPUT, note, key)
        unfilled = sorted(
            set(_UNFILLED_VARIABLE.findall(" ".join(str(value.get(name, "")) for name in ("subject", "html", "text"))))
        )
        if unfilled:
            self.note(
                NoteLevel.NEEDS_INPUT,
                f"Nothing fills {', '.join(unfilled)} here, so it prints blank or its default. Replace it with a "
                "person or event property.",
                key,
            )
        return {
            **base,
            "type": "function_email",
            "config": {"template_id": "template-email", "inputs": {"email": {"templating": "liquid", "value": value}}},
        }

    def _with_variables(
        self, key: str, text: str, variables: Mapping[str, Any], contact_variables: tuple[str, ...]
    ) -> str:
        for name, source in variables.items():
            replacement = self._variable_source(key, name, source)
            text = _fill_variable(text, name, replacement)
        # Resend fills these from the contact when a step doesn't, and a person's properties do the same job here.
        for name in contact_variables:
            if name not in variables:
                text = _fill_variable(text, name, f"person.properties.{_CONTACT_VARIABLE_PROPERTIES.get(name, name)}")
        return text

    def _variable_source(self, key: str, name: str, source: Any) -> str:
        reference = source.get("var") if isinstance(source, dict) else None
        if reference is None:
            text = json.dumps(source) if isinstance(source, bool) else str(source)
            literal = _liquid_literal(text)
            if literal is None:
                self.note(
                    NoteLevel.NEEDS_INPUT, f"PostHog can't keep the value of {name} as written. Add it again.", key
                )
                return f"variables.{name}"
            return literal
        return self._readable_path(key, name, str(reference)) or f"variables.{name}"

    def _readable_path(self, key: str, name: str, path: str) -> str | None:
        """Where a Resend variable reads from in PostHog, or None with a note if PostHog doesn't have it."""
        if path.startswith("event."):
            return f"event.properties.{_property_name(path.removeprefix('event.'))}"
        if path.startswith("contact.") and path.removeprefix("contact.") not in _CONTACT_ONLY_FIELDS:
            return f"person.properties.{_property_name(path.removeprefix('contact.'))}"
        self.note(NoteLevel.NEEDS_INPUT, _unreadable_message(name, path), key)
        return None

    def _conditions(self, key: str, config: dict[str, Any]) -> list[dict[str, Any]]:
        groups = self._condition_groups(key, config)
        if not groups:
            self.note(
                NoteLevel.NEEDS_INPUT,
                "PostHog couldn't read this condition, so everyone takes its first path for now. Set what it checks.",
                key,
            )
            self.condition_paths[key] = 1
            return [{"filters": {"properties": []}, "name": "Condition 1"}]
        self.condition_paths[key] = len(groups)
        return [
            {"filters": {"properties": properties}, "name": f"Condition {index + 1}"}
            for index, properties in enumerate(groups)
        ]

    def _condition_groups(
        self, key: str, config: dict[str, Any], *, in_wait: bool = False
    ) -> list[list[dict[str, Any]]]:
        groups = self._groups(key, config, in_wait)
        if len(groups) > _MAX_CONDITION_PATHS:
            self.note(
                NoteLevel.NEEDS_INPUT,
                f"This check needs more than {_MAX_CONDITION_PATHS} paths in PostHog, so only the first "
                f"{_MAX_CONDITION_PATHS} were kept. Rewrite it with fewer rules.",
                key,
            )
        return groups[:_MAX_CONDITION_PATHS]

    def _groups(self, key: str, config: dict[str, Any], in_wait: bool) -> list[list[dict[str, Any]]]:
        """The rule as "any of these groups, where all of a group's filters match", which is all PostHog can store."""
        kind = config.get("type")
        if kind == "rule":
            return self._rule_groups(key, config, in_wait)
        rules = [rule for rule in config.get("rules") or [] if isinstance(rule, dict)]
        # One group past the limit is enough to know the caller must cut, and keeps nested rules from growing.
        limit = _MAX_CONDITION_PATHS + 1
        if kind == "or":
            alternatives: list[list[dict[str, Any]]] = []
            for rule in rules:
                alternatives.extend(self._groups(key, rule, in_wait))
                if len(alternatives) >= limit:
                    break
            return alternatives[:limit]
        if kind == "and":
            combined: list[list[dict[str, Any]]] = [[]]
            for rule in rules:
                groups = self._groups(key, rule, in_wait)
                if groups:
                    combined = list(islice(([*left, *right] for left in combined for right in groups), limit))
            return [group for group in combined if group]
        return []

    def _rule_groups(self, key: str, rule: dict[str, Any], in_wait: bool) -> list[list[dict[str, Any]]]:
        field = str(rule.get("field") or "")
        operator = str(rule.get("operator") or "")
        namespace, _, raw_name = field.partition(".")
        name = _property_name(raw_name)
        property_type = {"contact": "person", "event": "event"}.get(namespace)
        value = rule.get("value")
        if property_type is None or not name or (namespace == "contact" and raw_name in _CONTACT_ONLY_FIELDS):
            self.note(NoteLevel.NEEDS_INPUT, f"{_unreadable_message(field, field)} This check was left out.", key)
            return []
        if isinstance(value, dict):
            comparison = self._variable_comparison(key, field, name, property_type, operator, value, in_wait)
            return [[comparison]] if comparison else []
        base = {"key": name, "type": property_type}
        if operator == "is_empty":
            # Resend's docs don't say whether "empty" means missing or blank, so either one counts.
            return [[{**base, "operator": "is_not_set"}], [{**base, "operator": "exact", "value": ""}]]
        if operator == "exists":
            return [[{**base, "operator": "is_set"}]]
        if value is None:
            if operator in ("eq", "neq"):
                return [[{**base, "operator": "is_not_set" if operator == "eq" else "is_set"}]]
            self.note(NoteLevel.NEEDS_INPUT, f"The check on {field} has no value. Set what it checks.", key)
            return []
        if operator == "starts_with":
            return [[{**base, "operator": "regex", "value": f"^{re.escape(str(value))}"}]]
        if operator == "ends_with":
            return [[{**base, "operator": "regex", "value": f"{re.escape(str(value))}$"}]]
        mapped = _OPERATORS.get(operator)
        if mapped is None:
            self.note(NoteLevel.NEEDS_INPUT, f"PostHog can't use the check {operator}. Set this condition.", key)
            return []
        return [[{**base, "operator": mapped, "value": value}]]

    def _variable_comparison(
        self, key: str, field: str, name: str, property_type: str, operator: str, value: dict[str, Any], in_wait: bool
    ) -> dict[str, Any] | None:
        """Comparing two properties needs a HogQL filter, because a property filter only holds a fixed value."""
        reference = str(value.get("var") or "")
        symbol = _COMPARISONS.get(operator)
        if not reference or symbol is None:
            self.note(
                NoteLevel.NEEDS_INPUT,
                f"PostHog can only compare {field} with a variable using equals or greater or less than. Set this check.",
                key,
            )
            return None
        if in_wait and reference.startswith("event."):
            self.note(
                NoteLevel.APPROXIMATED,
                f"Resend only ends this wait when {field} on the new event matches {reference} on the event that "
                "started the automation. A PostHog wait can't read that first event, so this check was left out and "
                "any event that passes the other checks ends the wait.",
                key,
            )
            return None
        readable = self._readable_path(key, field, reference)
        if readable is None:
            return None
        left = _hogql_property(property_type, name)
        right = _hogql_property(*_split_readable(readable))
        if operator in _NUMERIC_COMPARISONS:
            left, right = f"toFloat({left})", f"toFloat({right})"
        # Resend says a value that points at missing data never matches, and "!=" would match it.
        return {"key": f"{right} IS NOT NULL AND {left} {symbol} {right}", "type": "hogql"}

    def _wait(self, key: str, config: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        event_name = config.get("event_name")
        if not config.get("timeout"):
            self.note(
                NoteLevel.APPROXIMATED,
                "Resend sets no time limit here, and PostHog needs one, so this waits at most 30 days.",
                key,
            )
            timeout = _duration(_MAX_WAIT_SECONDS)
        else:
            timeout = self._duration(key, config, "timeout", cap=_MAX_WAIT_SECONDS)
        events = []
        if event_name:
            filter_rule = config.get("filter_rule")
            groups = self._condition_groups(key, filter_rule, in_wait=True) if isinstance(filter_rule, dict) else []
            events = [
                {
                    "name": event_name,
                    "filters": {
                        "events": [
                            {"id": event_name, "name": event_name, "type": "events", "order": 0, "properties": group}
                        ]
                    },
                }
                for group in groups or [[]]
            ]
            self.note(NoteLevel.NEEDS_INPUT, f"Send {event_name} to PostHog too, or this step always times out.", key)
        else:
            self.note(NoteLevel.NEEDS_INPUT, "Pick the event this step waits for.", key)
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
            self._note_extra_paths(None, first[1:])
        else:
            edges.append({"from": TRIGGER_ID, "to": _EXIT_ID, "type": "continue"})
        for key, step in self.steps.items():
            if key not in actions:
                continue
            step_type = step.get("type")
            links = self.links.get(key, [])
            if step_type == "contact_delete":
                self._note_extra_paths(key, links)
            elif step_type == "condition":
                paths = self.condition_paths[key]
                edges.extend(self._branch_edges(key, links, "condition_met", "condition_not_met", actions, paths))
            elif step_type == "wait_for_event":
                edges.extend(self._branch_edges(key, links, "event_received", "timeout", actions, 1))
            else:
                target = self._next_kept(links[0][0], actions) if links else _EXIT_ID
                self._note_extra_paths(key, links[1:])
                source = key
                if key in self.second_steps:
                    edges.append({"from": key, "to": self.second_steps[key], "type": "continue"})
                    source = self.second_steps[key]
                edges.append({"from": source, "to": target, "type": "continue"})
        return edges

    def _note_extra_paths(self, key: str | None, links: list[tuple[str, str]]) -> None:
        if links:
            targets = ", ".join(target for target, _ in links)
            self.note(
                NoteLevel.UNSUPPORTED,
                f"PostHog couldn't keep this step's path to {targets}. Add it if you need it.",
                key,
            )

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
        used = {(match_target, match_type), (other_target, other_type)}
        self._note_extra_paths(key, [link for link in links if link not in used])
        matched = self._next_kept(match_target, actions) if match_target else _EXIT_ID
        other = self._next_kept(other_target, actions) if other_target else _EXIT_ID
        # A condition with "or" rules becomes several conditions, and PostHog gives each one its own path.
        return [
            *({"from": key, "to": matched, "type": "branch", "index": index} for index in range(max(branches, 1))),
            {"from": key, "to": other, "type": "continue"},
        ]


_LIQUID_TAG = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
_LIQUID_STRING = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')")


def _literal_liquid(text: str) -> str:
    # The email is rendered as Liquid, so a header value from Resend must not run as a tag.
    return re.sub(r"\{\{|\{%", lambda match: f'{{{{ "{match.group(0)}" }}}}', text)


def _fill_variable(text: str, name: str, replacement: str) -> str:
    """Replaces references to `variables.NAME` inside Liquid tags, leaving body copy and quoted strings alone."""
    reference = re.compile(rf"\bvariables\.{re.escape(name)}(?![\w-])")

    def fill_tag(tag: re.Match[str]) -> str:
        # Odd parts are string literals. A callable keeps a backslash in the replacement from reading as an escape.
        parts = _LIQUID_STRING.split(tag.group(0))
        return "".join(
            part if index % 2 else reference.sub(lambda _: replacement, part) for index, part in enumerate(parts)
        )

    return _LIQUID_TAG.sub(fill_tag, text)


def _rename_reserved_keys(steps: Mapping[str, Any]) -> dict[str, str]:
    renamed: dict[str, str] = {}
    for key in steps:
        if key in (TRIGGER_ID, _EXIT_ID):
            new_key = f"{key}_step"
            while new_key in steps or new_key in renamed.values():
                new_key += "_"
            renamed[key] = new_key
    return renamed


def _property_name(path: str) -> str:
    return path.removeprefix("properties.")


def _liquid_literal(text: str) -> str | None:
    if _UNSAFE_IN_LITERAL.search(text):
        return None
    if '"' not in text:
        return f'"{text}"'
    if "'" not in text:
        return f"'{text}'"
    return None


def _step_name(key: str, step_type: str) -> str:
    return f"{step_type.replace('_', ' ').capitalize()} ({key})"[:400]


def _sender(email: str, name: str, integration_id: int | None) -> dict[str, Any]:
    if integration_id is not None:
        return {"integrationId": integration_id, "email": email, "name": name}
    return {"email": email, "name": name}


def _unreadable_message(name: str, path: str) -> str:
    if path.startswith("wait_events."):
        return (
            f"{name} reads {path}, and later steps in PostHog can't read data from the event a wait received. "
            "Set where it comes from."
        )
    return f"{name} reads {path}, which PostHog doesn't have. Set where it comes from."


def _hog_path(path: str) -> str:
    first, *rest = path.split(".")
    parts = [first]
    for part in rest:
        parts.append(f".{part}" if _HOG_IDENTIFIER.match(part) else f"[{json.dumps(part)}]")
    return "".join(parts)


def _split_readable(path: str) -> tuple[str, str]:
    scope, name = path.split(".properties.", 1)
    return ("person" if scope == "person" else "event"), name


def _hogql_property(property_type: str, name: str) -> str:
    prefix = "person.properties" if property_type == "person" else "properties"
    return f"{prefix}.{escape_hogql_identifier(name)}"
