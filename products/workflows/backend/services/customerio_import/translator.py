"""A Customer.io automation, as its Journeys UI API returns it, turned into a draft PostHog workflow.

The input is `GET /v1/environments/:id/campaigns/:id` (the `campaign` and top-level `actions`), plus the templates
its message actions point at. Every setting that has no PostHog equivalent is left out and named in the notes, so
the team can review the draft before enabling it. Nothing about people is read.
"""

import re
import json
import secrets
from collections import deque
from collections.abc import Iterator
from email.utils import parseaddr
from typing import Any

from posthog.dataclasses import frozen

from products.workflows.backend.facade.contracts import (
    CampaignSource,
    ImportNote,
    ImportOptions,
    SnippetRoom,
    TranslatedWorkflow,
)
from products.workflows.backend.facade.enums import WorkflowImportNoteLevel as NoteLevel
from products.workflows.backend.services.customerio_import import conditions, liquid

TRIGGER_ID = "trigger_node"
_EXIT_ID = "exit_node"
_MAX_DELAY_SECONDS = 365 * 86400
_MAX_WAIT_SECONDS = 30 * 86400
# Unit, seconds per unit, and the largest amount a workflow accepts in that unit.
_DURATION_UNITS: tuple[tuple[str, int, int | None], ...] = (
    ("d", 86400, None),
    ("h", 3600, 24),
    ("m", 60, 60),
    ("s", 1, 60),
)
_CREDENTIAL_HEADER = re.compile(r"auth|api[-_]?key|token|secret|password|cookie|signature", re.IGNORECASE)
_DAY_NAMES = {
    "Mon": "monday",
    "Tue": "tuesday",
    "Wed": "wednesday",
    "Thu": "thursday",
    "Fri": "friday",
    "Sat": "saturday",
    "Sun": "sunday",
}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]
_LAYOUT_CONTENT = re.compile(r"\{\{-?\s*content\s*-?\}\}")
_LIQUID_TAG = re.compile(r"\{\{.{0,500}?\}\}|\{%.{0,500}?%\}", re.DOTALL)
_SANS_SERIF = "font-family: Arial, Helvetica, sans-serif;"
_STATIC_SEGMENT_TYPES = {"static", "manual"}
_SEGMENT_IDS = re.compile(r"\b(segments?) (\d+(?:, \d+)*)\b")
_CHANNEL_NAMES = {
    "push_action": "push notification",
    "twilio_action": "SMS",
    "sms_action": "SMS",
    "in_app_action": "in-app message",
    "inbox_action": "inbox message",
    "whatsapp_action": "WhatsApp message",
    "line_action": "LINE message",
    "urban_airship_action": "push notification",
    "slack_action": "Slack message",
}


class _Builder:
    def __init__(self, source: CampaignSource, options: ImportOptions, snippet_room: SnippetRoom) -> None:
        self.campaign = source.campaign
        self.source_actions = {str(action["id"]): action for action in source.actions if action.get("id") is not None}
        self.templates = source.templates
        self.options = options
        self.notes: list[ImportNote] = []
        self.actions: dict[str, dict[str, Any]] = {}
        # Outgoing links per source action id: (target source id, edge type, index).
        self.links: dict[str, list[tuple[str, str, int | None]]] = {}
        self.snippet_room = snippet_room

    def note(self, level: NoteLevel, message: str, action: dict[str, Any] | None = None) -> None:
        self.notes.append(
            ImportNote(
                level=level,
                message=_SEGMENT_IDS.sub(self._name_segments, message),
                step_id=action["id"] if action else None,
                step_name=action.get("name") if action else None,
            )
        )

    def build(self) -> TranslatedWorkflow:
        source_edges = [edge for edge in self.campaign.get("edges") or [] if isinstance(edge, dict)]
        for edge in source_edges:
            # Customer.io can send a branch index as a string, and every later check compares numbers.
            index = int(edge["index"]) if edge.get("index") is not None else None
            self.links.setdefault(str(edge.get("from")), []).append(
                (str(edge.get("to")), str(edge.get("type") or "continue"), index)
            )

        workflow_actions_order = [str(action_id) for action_id in self.campaign.get("workflow_action_ids") or []]
        ordered_ids = workflow_actions_order or list(self.source_actions)
        graph_ids = [
            action_id
            for action_id in ordered_ids
            if action_id in self.source_actions and self.source_actions[action_id].get("type") != "trigger"
        ]
        incoming = {target for links in self.links.values() for target, _, _ in links}
        roots = [action_id for action_id in graph_ids if action_id not in incoming]

        trigger = self._trigger()
        posthog_actions: list[dict[str, Any]] = [
            {"id": TRIGGER_ID, "name": "Trigger", "description": "", "type": "trigger", "config": trigger}
        ]
        for action_id in graph_ids:
            translated = self._action(self.source_actions[action_id])
            if translated is not None:
                self.actions[action_id] = translated

        edges = self._edges(roots)
        posthog_actions.extend(self.actions.values())
        if any(edge["to"] == _EXIT_ID for edge in edges):
            posthog_actions.append(_exit_action(_EXIT_ID, "Exit"))
        pruned = _prune_unreachable(posthog_actions, edges)
        posthog_actions, edges = pruned.actions, pruned.edges
        kept_ids = {action["id"] for action in posthog_actions}

        workflow: dict[str, Any] = {
            "name": (self.campaign.get("name") or "Imported from Customer.io")[:400],
            "description": f"Imported from Customer.io automation {self.campaign.get('id')}.",
            "trigger": trigger,
            "actions": posthog_actions,
            "edges": edges,
            "exit_condition": self._exit_condition(),
            # Sent even when empty, so a re-import clears a goal or a re-entry limit the automation dropped.
            "conversion": self._conversion(),
            "trigger_masking": self._trigger_masking(),
        }
        self._campaign_notes()
        self._static_segment_notes()
        # A step that no path reaches, like a language variant behind its default, is not in the draft.
        notes = tuple(note for note in self.notes if note.step_id is None or note.step_id in kept_ids)
        return TranslatedWorkflow(
            source_id=str(self.campaign.get("id")),
            name=workflow["name"],
            workflow=workflow,
            notes=notes,
        )

    def _trigger(self) -> dict[str, Any]:
        kind = self.campaign.get("type")
        if kind in ("transactional", "form") and self.campaign.get("event"):
            if self.campaign.get("event_type") not in (None, "", "event"):
                self.note(
                    NoteLevel.UNSUPPORTED,
                    f"Customer.io starts this automation on a {self.campaign['event_type']} event, which PostHog "
                    "does not receive. Pick the event that starts it in PostHog.",
                )
                return _empty_trigger()
            name = str(self.campaign["event"])
            properties, skipped = conditions.translate_filter_tree(self.campaign.get("attribute_filters"), "event")
            for description in skipped:
                self.note(NoteLevel.UNSUPPORTED, f"The trigger's event filter `{description}` was left out.")
            event: dict[str, Any] = {"id": name, "name": name, "type": "events", "order": 0}
            if properties:
                event["properties"] = properties
            trigger: dict[str, Any] = {"type": "event", "filters": {"events": [event]}}
            self._audience_filter(trigger)
            return trigger
        if kind in ("seg_attr", "behavioral"):
            return self._segment_trigger()
        labels = {
            "date": "a date attribute",
            "webhook": "an incoming webhook",
            "triggered_broadcast": "an API call (API-triggered broadcast)",
            "relationship": "a relationship change",
            "object": "an object change",
            "rel_seg_attr": "a relationship segment",
        }
        self.note(
            NoteLevel.UNSUPPORTED,
            f"Customer.io starts this automation on {labels.get(str(kind), f'a `{kind}` trigger')}, which has no "
            "PostHog trigger yet. Pick how it starts in PostHog.",
        )
        return _empty_trigger()

    def _segment_trigger(self) -> dict[str, Any]:
        trigger_tree = self.campaign.get("trigger")
        segments = _segment_references(trigger_tree)
        attributes = _attribute_leaves(trigger_tree)
        if len(segments) == 1 and not attributes and segments[0] in self.options.segment_cohorts:
            inverse = _segment_is_inverse(trigger_tree)
            return {
                "type": "cohort",
                "cohort_id": self.options.segment_cohorts[segments[0]],
                "transition": "left" if inverse else "entered",
            }
        described = [f"in segment {segment}" for segment in segments] + [
            conditions.describe(attribute) for attribute in attributes
        ]
        what = "; ".join(described) or "a segment"
        self.note(
            NoteLevel.NEEDS_INPUT,
            f"Customer.io starts this automation when a person matches: {what}. Create a realtime cohort with "
            "these conditions and start the workflow when a person joins it.",
        )
        return _empty_trigger()

    def _audience_filter(self, trigger: dict[str, Any]) -> None:
        # `filters` on an event-triggered automation is segment membership the person must have to enter.
        audience = conditions.decode(self.campaign.get("filters"))
        if not audience:
            return
        translated = conditions.translate_condition(audience, self.options.segment_cohorts)
        if translated.properties:
            trigger["filters"]["properties"] = list(translated.properties)
        for description in translated.skipped:
            self.note(
                NoteLevel.NEEDS_INPUT,
                f"Only people {description} can enter in Customer.io. Add a cohort filter to the trigger for it.",
            )

    def _trigger_masking(self) -> dict[str, Any] | None:
        mode = self.campaign.get("restart_mode")
        if self.campaign.get("type") not in ("seg_attr", "behavioral", "rel_seg_attr"):
            return None
        if mode == "none":
            return {"hash": "{person.id}", "ttl": None, "threshold": None}
        if mode == "interval" and self.campaign.get("restart_min_interval"):
            return {"hash": "{person.id}", "ttl": int(self.campaign["restart_min_interval"]), "threshold": None}
        return None

    def _conversion(self) -> dict[str, Any] | None:
        if not self.campaign.get("conversion"):
            return None
        conversion_type = self.campaign.get("conversion_type")
        window = _duration(self.campaign.get("conversion_window") or 0)
        if conversion_type == "perform_event" and not self.campaign.get("conversion_event_name"):
            # New Customer.io automations have the goal switched on with no event until someone picks one.
            return None
        if conversion_type != "perform_event":
            self.note(
                NoteLevel.UNSUPPORTED,
                "The goal counts people entering or leaving a segment. Set a conversion goal on an event instead.",
            )
            return None
        name = str(self.campaign["conversion_event_name"])
        event: dict[str, Any] = {"id": name, "name": name, "type": "events", "order": 0}
        properties: list[dict[str, Any]] = []
        event_filters = self.campaign.get("conversion_event_filters")
        if _has_alternatives(event_filters):
            # A flat AND list can't hold "any of", and dropping the OR would make the goal match nothing.
            self.note(
                NoteLevel.UNSUPPORTED,
                "The goal's event filters match any of several conditions, which PostHog goals can't express. "
                "They were left out, so every conversion event counts. Narrow the goal by hand.",
            )
            event_filters = None
        for leaf in _foreign_event_leaves(event_filters):
            filters = conditions.property_filters(leaf, "event")
            if filters is None:
                self.note(NoteLevel.UNSUPPORTED, f"The goal's event filter `{conditions.describe(leaf)}` was left out.")
            else:
                properties.extend(filters)
        if properties:
            event["properties"] = properties
        if self.campaign.get("conversion_action") in ("opening", "clicking"):
            self.note(
                NoteLevel.APPROXIMATED,
                f"Customer.io counts a conversion only after the person is {self.campaign['conversion_action']} a "
                "message. PostHog counts every conversion inside the window.",
            )
        conversion: dict[str, Any] = {"filters": [], "events": [{"name": name, "filters": {"events": [event]}}]}
        if window:
            conversion["window"] = window
        return conversion

    def _exit_condition(self) -> str:
        on_conversion = bool(self.campaign.get("exit_on_conversion_matched")) or self._exits_match_goal()
        on_trigger = bool(self.campaign.get("exit_on_trigger_or_filter_not_matched")) and self.campaign.get("type") in (
            "seg_attr",
            "behavioral",
        )
        if on_conversion and on_trigger:
            return "exit_on_trigger_not_matched_or_conversion"
        if on_conversion:
            return "exit_on_conversion"
        if on_trigger:
            return "exit_on_trigger_not_matched"
        return "exit_only_at_end"

    def _exits_match_goal(self) -> bool:
        exits = self.campaign.get("global_exit_conditions") or []
        goal = self.campaign.get("conversion_event_name") if self.campaign.get("conversion") else None
        goal_is_bare = not self.campaign.get("conversion_event_filters")
        matched = False
        for exit_condition in exits:
            names = _exit_event_names(exit_condition)
            if goal and goal_is_bare and names == [goal] and _is_bare_event(exit_condition):
                matched = True
            else:
                self.note(
                    NoteLevel.UNSUPPORTED,
                    f"Customer.io removes people from this automation when: {conditions.describe(exit_condition)}. "
                    "PostHog can exit people on the conversion goal or when they stop matching the trigger.",
                )
        return matched

    def _campaign_notes(self) -> None:
        if self.campaign.get("frequency_cap_id") or self.campaign.get("use_message_limits"):
            self.note(
                NoteLevel.APPROXIMATED,
                "Customer.io message limits apply to this automation. Set them in PostHog's sending rules.",
            )
        throttle = self.campaign.get("message_throttle") or {}
        if throttle.get("enabled"):
            self.note(
                NoteLevel.APPROXIMATED,
                "Customer.io throttles this automation's sends. Set an email sending limit on the workflow.",
            )

    def _name_segments(self, match: re.Match[str]) -> str:
        labels = [self._segment_label(segment_id) for segment_id in match.group(2).split(", ")]
        return f"{match.group(1)} {', '.join(labels)}"

    def _segment_label(self, segment_id: str) -> str:
        segment = self.options.segments.get(segment_id)
        return f'"{segment.name}" ({segment_id})' if segment and segment.name else segment_id

    def _static_segment_notes(self) -> None:
        trees: list[Any] = [self.campaign.get("trigger"), self.campaign.get("global_exit_conditions")]
        trees.append(conditions.decode(self.campaign.get("filters")))
        for action in self.source_actions.values():
            trees.append(conditions.decode(action.get("preconditions")))
            trees.append(conditions.decode(action.get("conditions")))
            trees.extend(conditions.decode(item) for item in action.get("multi_conditions") or [])
        referenced = dict.fromkeys(segment for tree in trees for segment in _segment_references(tree))
        for segment_id in referenced:
            segment = self.options.segments.get(segment_id)
            if segment is None or segment.type not in _STATIC_SEGMENT_TYPES:
                continue
            self.note(
                NoteLevel.NEEDS_INPUT,
                f"Customer.io segment {self._segment_label(segment_id)} is a static list. Workflows cannot check a "
                "static cohort, so rebuild it as person property conditions or a realtime cohort.",
            )

    def _action(self, source: dict[str, Any]) -> dict[str, Any] | None:
        kind = source.get("type")
        action_id = f"cio_{source['id']}"
        name = _plain_name(source.get("name")) or str(kind or "Step")
        base: dict[str, Any] = {"id": action_id, "name": name, "description": ""}
        translated: dict[str, Any] | None
        match kind:
            case "email_action":
                translated = {**base, **self._email(source, base)}
            case "webhook_action":
                translated = {**base, **self._webhook(source, base)}
            case "attribute_update_action":
                translated = self._attribute_update(source, base)
            case "create_event_action":
                translated = self._create_event(source, base)
            case "delay_seconds_action":
                translated = {
                    **base,
                    "type": "delay",
                    "config": {"delay_duration": self._delay(base, source.get("delay"))},
                }
            case "randomized_delay_action":
                low, high = int(source.get("min_delay") or 0), int(source.get("max_delay") or 0)
                middle = (low + high) // 2
                translated = {**base, "type": "delay", "config": {"delay_duration": self._delay(base, middle)}}
                self.note(
                    NoteLevel.APPROXIMATED,
                    f"Customer.io waits a random time between {_duration(low)} and {_duration(high)}. "
                    f"PostHog waits {_duration(middle)}.",
                    base,
                )
            case "delay_time_window_action":
                translated = {**base, "type": "wait_until_time_window", "config": self._time_window(source)}
            case "conditional_wait_action":
                translated = self._wait(source, base)
            case "conditional_branch_action":
                translated = self._branch(source, base, [source.get("conditions")])
            case "multi_split_branch_action":
                translated = self._branch(source, base, list(source.get("multi_conditions") or []))
            case "random_cohort_branch_action":
                translated = self._random_cohort(source, base)
            case "exit_action":
                translated = _exit_action(action_id, name if source.get("name") else "Exit")
            case "multi_lang_branch_action":
                self.note(
                    NoteLevel.APPROXIMATED,
                    f"The language split `{name}` sends everyone its default-language message. Add the other "
                    "languages with a branch on the person's language property.",
                )
                return None
            case "filter_match_delay_action":
                # People pass straight through to the only next step in PostHog.
                return None
            case _:
                label = _CHANNEL_NAMES.get(str(kind), f"`{kind}` step")
                self.note(
                    NoteLevel.UNSUPPORTED,
                    f"The {label} `{name}` has no PostHog equivalent and was left out.",
                )
                return None
        if translated is not None:
            self._preconditions(source, translated)
        return translated

    def _preconditions(self, source: dict[str, Any], action: dict[str, Any]) -> None:
        precondition = conditions.decode(source.get("preconditions"))
        if not precondition:
            return
        translated = conditions.translate_condition(precondition, self.options.segment_cohorts)
        if translated.properties:
            action["filters"] = {"properties": list(translated.properties)}
        for description in translated.skipped:
            self.note(
                NoteLevel.UNSUPPORTED,
                f"Customer.io skips this step unless `{description}`. That check was left out.",
                action,
            )

    def _template(self, source: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        template_id = source.get("template_id")
        template = self.templates.get(str(template_id)) if template_id is not None else None
        if template is None:
            self.note(
                NoteLevel.NEEDS_INPUT,
                "The message content was not part of the import. Write it in PostHog, or import again with the "
                f"Customer.io template {template_id}.",
                action,
            )
            return {}
        return template

    def _liquid(self, text: str | None, action: dict[str, Any], field: str) -> str:
        rewritten = liquid.rewrite(text, self.options.snippets, self.snippet_room)
        for name in rewritten.missing_snippets:
            self.note(
                NoteLevel.NEEDS_INPUT,
                f"The {field} includes the Customer.io snippet `{name}`, which was not part of the import or was too "
                "large to copy in. "
                "Replace it with the snippet's content.",
                action,
            )
        for name in rewritten.unsupported_globals:
            self.note(
                NoteLevel.UNSUPPORTED,
                f"The {field} uses Customer.io's `{name}` Liquid variables, which PostHog does not have.",
                action,
            )
        return rewritten.text

    def _email(self, source: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        template = self._template(source, action)
        recipient = template.get("recipient") or source.get("recipient") or "{{customer.email}}"
        html = self._liquid(self._with_layout(template, action), action, "email body")
        email: dict[str, Any] = {
            "to": {"email": self._liquid(recipient, action, "recipient"), "name": ""},
            "from": self._sender(template, action),
            "replyTo": self._address(template, "reply_to_identity_id", "reply_to_id", "reply_to").email,
            "subject": self._liquid(template.get("subject") or source.get("subject") or "", action, "subject"),
            "preheader": self._liquid(template.get("preheader_text") or "", action, "preheader"),
            "html": html,
        }
        if template.get("body_plain"):
            email["text"] = self._liquid(template["body_plain"], action, "plain-text body")
        if not template:
            # A draft needs a subject and a body to save. The note about the missing content asks for the real ones.
            email["subject"] = email["subject"] or action["name"]
            email["html"] = "<p>This email's content was not imported from Customer.io.</p>"
        if template.get("editor") in ("bee", "parcel", "wysiwyg"):
            self.note(
                NoteLevel.APPROXIMATED,
                "The email is imported as HTML. The Customer.io visual design is not editable in PostHog's "
                "visual editor, so edit it in the code editor.",
                action,
            )
        if source.get("sending_state") == "draft":
            self.note(
                NoteLevel.APPROXIMATED,
                "Customer.io holds this message for review before sending. PostHog sends it as soon as the step runs.",
                action,
            )
        config: dict[str, Any] = {
            "template_id": "template-email",
            "inputs": {"email": {"templating": "liquid", "value": email}},
        }
        self._category(source, config, action)
        if source.get("tracked") is False:
            config["tracking_enabled"] = False
        return {"type": "function_email", "config": config}

    def _with_layout(self, template: dict[str, Any], action: dict[str, Any]) -> str:
        body = template.get("body") or ""
        layout_id = template.get("layout_id")
        layout = self.options.layouts.get(str(layout_id)) if layout_id else None
        if layout is None and isinstance(template.get("layout"), str):
            layout = template["layout"]
        if layout and _LAYOUT_CONTENT.search(layout):
            # A comment in the layout shows up as text in the plain-text version of the email.
            return _LAYOUT_CONTENT.sub(lambda _: body, _strip_comments(layout), count=1)
        if layout_id:
            self.note(
                NoteLevel.NEEDS_INPUT,
                f"Customer.io wraps this email in layout {layout_id}, which was not part of the import. Import "
                "again with the layout, or add its header and footer to the HTML.",
                action,
            )
        if body and "<html" not in body.lower() and "font-family" not in body.lower():
            # With no layout, mail clients fall back to a serif font such as Times.
            return f'<div style="{_SANS_SERIF}">{body}</div>'
        return body

    def _address(self, template: dict[str, Any], *keys: str) -> "_Address":
        """The email address and display name a template names under any of `keys`: an identity id or an address."""
        for key in keys:
            value = template.get(key)
            if value in (None, ""):
                continue
            address = self.options.sender_addresses.get(str(value))
            name, email = parseaddr(address if address is not None else str(value))
            if "@" in email:
                return _Address(email=email, name=name)
        return _Address(email="", name="")

    def _sender(self, template: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        if not template:
            return {"email": "", "name": ""}
        found = self._address(template, "from_identity_id", "from_id", "from")
        sender = self.options.senders.get(found.email.lower()) if found.email else None
        if sender is not None:
            return {"integrationId": sender.integration_id, "email": sender.email, "name": found.name or sender.name}
        if found.email:
            self.note(
                NoteLevel.NEEDS_INPUT,
                f"Customer.io sends this email from {found.email}, which is not a PostHog email sender yet. Add it "
                "as a sender, or choose another one.",
                action,
            )
        else:
            self.note(NoteLevel.NEEDS_INPUT, "Choose the email sender.", action)
        return {"email": found.email, "name": found.name}

    def _category(self, source: dict[str, Any], config: dict[str, Any], action: dict[str, Any]) -> None:
        topic_id = source.get("subscription_topic_id")
        if topic_id:
            category = self.options.topic_categories.get(str(topic_id))
            if category is not None:
                config["message_category_id"] = category.id
                config["message_category_type"] = category.category_type
                return
            self.note(
                NoteLevel.NEEDS_INPUT,
                f"Customer.io sends this email under subscription topic {topic_id}, which has no PostHog message "
                "category. Import your Customer.io topics with Import from Customer.io on the Opt-outs tab, then "
                "import again, or pick a category.",
                action,
            )
        if source.get("send_to_unsubscribed"):
            config["message_category_type"] = "transactional"

    def _webhook(self, source: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        template = self._template(source, action)
        body_text = self._liquid(template.get("body") or "", action, "request body")
        headers: dict[str, str] = {}
        secret_headers: dict[str, str] = {}
        for header in template.get("headers") or []:
            if not isinstance(header, dict) or not header.get("name"):
                continue
            name, value = str(header["name"]), str(header.get("value") or "")
            if not _CREDENTIAL_HEADER.search(name):
                headers[name] = self._liquid(value, action, "headers")
            elif "{{" in value or "{%" in value:
                self.note(
                    NoteLevel.NEEDS_INPUT,
                    f"The `{name}` header holds a credential built with Liquid, which secret headers don't run. "
                    "It was left out. Add its value under Secret headers.",
                    action,
                )
            else:
                secret_headers[name] = value
        inputs: dict[str, Any] = {
            "url": {"value": self._liquid(template.get("url") or "", action, "URL"), "templating": "liquid"},
            "method": {"value": str(template.get("request_method") or "POST").upper()},
            "headers": {"value": headers, "templating": "liquid"},
        }
        if secret_headers:
            inputs["secret_headers"] = {"value": secret_headers}
        if body_text:
            try:
                inputs["body"] = {"value": _json_with_liquid(body_text), "templating": "liquid"}
            except ValueError:
                # Liquid outside a JSON string, like `{% if %}` around a key, makes the stored body invalid JSON.
                self.note(
                    NoteLevel.NEEDS_INPUT,
                    "The request body is not valid JSON before Liquid runs, so it was not imported. Rebuild it as JSON.",
                    action,
                )
        if not template.get("url"):
            self.note(NoteLevel.NEEDS_INPUT, "Set the webhook URL.", action)
        return {"type": "function", "config": {"template_id": "template-webhook", "inputs": inputs}}

    def _attribute_update(self, source: dict[str, Any], base: dict[str, Any]) -> dict[str, Any] | None:
        if source.get("sub_type") == "journey_attr_update":
            self.note(
                NoteLevel.UNSUPPORTED,
                f"`{base['name']}` sets a journey attribute, which PostHog has no equivalent for. It was left out.",
            )
            return None
        properties = self._template_properties(self._template(source, base), base)
        if not properties:
            self.note(NoteLevel.NEEDS_INPUT, "Set the person properties this step updates.", base)
        return {
            **base,
            "type": "function",
            "config": {
                "template_id": "template-posthog-update-person-properties",
                "inputs": {
                    "distinct_id": {"value": "{{ event.distinct_id }}", "templating": "liquid"},
                    "set_properties": {"value": properties, "templating": "liquid"},
                },
            },
        }

    def _create_event(self, source: dict[str, Any], base: dict[str, Any]) -> dict[str, Any] | None:
        event_name: Any = source.get("event_name")
        # The editor stores the name as JSON, like `{"type": "static", "value": "signed_up"}`.
        if isinstance(event_name, str) and event_name.lstrip().startswith("{"):
            try:
                event_name = json.loads(event_name)
            except ValueError:
                pass
        if isinstance(event_name, dict):
            event_name = event_name.get("value")
        if not event_name:
            self.note(NoteLevel.UNSUPPORTED, f"`{base['name']}` sends an event with no name, so it was left out.")
            return None
        inputs: dict[str, Any] = {
            "event": {"value": self._liquid(str(event_name), base, "event name"), "templating": "liquid"},
            "distinct_id": {"value": "{{ event.distinct_id }}", "templating": "liquid"},
        }
        if source.get("template_id") is not None:
            properties = self._template_properties(self._template(source, base), base)
            if properties:
                inputs["properties"] = {"value": properties, "templating": "liquid"}
        return {
            **base,
            "type": "function",
            "config": {"template_id": "template-posthog-capture", "inputs": inputs},
        }

    def _template_properties(self, template: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        """The `[{name, type, value}]` list that attribute update and create event steps keep in their template."""
        attributes: Any = []
        for raw in (template.get("body"), template.get("body_json")):
            if not raw:
                continue
            try:
                attributes = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            if attributes:
                break
        properties: dict[str, Any] = {}
        for attribute in attributes if isinstance(attributes, list) else []:
            if not isinstance(attribute, dict) or not attribute.get("name"):
                continue
            value = attribute.get("value")
            if attribute.get("type") == "profile_attribute":
                value = "{{customer." + str(value or "") + "}}"
            if value is None or isinstance(value, str):
                properties[str(attribute["name"])] = self._liquid(value or "", base, "property value")
            else:
                properties[str(attribute["name"])] = value
        return properties

    def _delay(self, action: dict[str, Any], seconds: Any) -> str:
        total = int(seconds or 0)
        if total > _MAX_DELAY_SECONDS:
            self.note(
                NoteLevel.APPROXIMATED, f"Delays are capped at 365 days, so {_duration(total)} became 365d.", action
            )
            total = _MAX_DELAY_SECONDS
        return _duration(total) or "0m"

    def _time_window(self, source: dict[str, Any]) -> dict[str, Any]:
        days = [_DAY_NAMES[day] for day in str(source.get("days") or "").split(":") if day in _DAY_NAMES]
        day: Any = "any" if not days or len(days) == 7 else days
        if days == _WEEKDAYS:
            day = "weekday"
        elif sorted(days) == ["saturday", "sunday"]:
            day = "weekend"
        start, end = source.get("start_time"), source.get("end_time")
        config: dict[str, Any] = {"day": day, "time": [start, end] if start and end else "any"}
        zone = source.get("zone")
        if zone == "customer_time_zone":
            config.update(
                {"timezone": None, "use_person_timezone": True, "fallback_timezone": source.get("fallback_zone")}
            )
        else:
            config["timezone"] = zone or None
        return config

    def _wait(self, source: dict[str, Any], base: dict[str, Any]) -> dict[str, Any] | None:
        encoded = [item for item in source.get("multi_conditions") or [] if item]
        decoded = [conditions.decode(item) for item in encoded]
        events: list[dict[str, Any]] = []
        properties: list[dict[str, Any]] = []
        property_conditions = 0
        for index, condition in enumerate(decoded):
            if condition is None:
                self.note(
                    NoteLevel.UNSUPPORTED, f"Wait condition {index + 1} could not be read and was left out.", base
                )
                continue
            translated = conditions.translate_condition(condition, self.options.segment_cohorts)
            for description in translated.skipped:
                self.note(NoteLevel.UNSUPPORTED, f"The wait for `{description}` was left out.", base)
            if translated.events:
                # Properties next to a waited-for event filter that event, which PostHog puts on the event itself.
                for event in translated.events:
                    event["properties"] = [*event.get("properties", []), *translated.properties]
                events.extend({"name": event["name"], "filters": {"events": [event]}} for event in translated.events)
            elif translated.properties:
                property_conditions += 1
                if property_conditions == 1:
                    properties = list(translated.properties)
        if property_conditions > 1:
            self.note(
                NoteLevel.APPROXIMATED,
                "Customer.io waits for any of several property conditions. PostHog waits for the first one only.",
                base,
            )
        if source.get("delay_event_attr"):
            self.note(
                NoteLevel.UNSUPPORTED,
                f"Customer.io also stops waiting at the date in `{source['delay_event_attr']}`. That was left out.",
                base,
            )

        delay = int(source.get("delay") or 0)
        if delay <= 0 or source.get("exit_type") == "never":
            self.note(
                NoteLevel.APPROXIMATED,
                "Customer.io waits with no time limit. PostHog waits at most 30 days, then takes the timeout path.",
                base,
            )
            delay = _MAX_WAIT_SECONDS
        elif delay > _MAX_WAIT_SECONDS:
            self.note(NoteLevel.APPROXIMATED, f"Waits are capped at 30 days, so {_duration(delay)} became 30d.", base)
            delay = _MAX_WAIT_SECONDS

        # Customer.io gives each condition its own path and puts the timeout last. PostHog has one path for
        # "the condition matched", so every condition path has to lead to the same step.
        links = sorted(self.links.get(str(source["id"]), []), key=lambda link: link[2] or 0)
        condition_count = len(encoded)
        condition_targets = [target for target, _, index in links if index is not None and index < condition_count]
        timeout_targets = [target for target, _, index in links if index is not None and index >= condition_count]
        if len(set(condition_targets)) > 1:
            self.note(
                NoteLevel.APPROXIMATED,
                "Each wait condition leads to a different step in Customer.io. In PostHog every match takes the "
                "first condition's path, so check the other paths.",
                base,
            )
        new_links: list[tuple[str, str, int | None]] = []
        if condition_targets:
            new_links.append((condition_targets[0], "branch", 0))
        new_links.append((timeout_targets[-1] if timeout_targets else _EXIT_ID, "continue", None))
        self.links[str(source["id"])] = new_links
        if not events and not properties:
            self.note(NoteLevel.NEEDS_INPUT, "Set what this step waits for.", base)
        return {
            **base,
            "type": "wait_until_condition",
            "config": {
                "condition": {"filters": {"properties": properties} if properties else None},
                "events": events,
                "max_wait_duration": _duration(delay),
            },
        }

    def _branch(self, source: dict[str, Any], base: dict[str, Any], encoded: list[Any]) -> dict[str, Any]:
        posthog_conditions: list[dict[str, Any]] = []
        for index, item in enumerate(encoded):
            decoded = conditions.decode(item)
            translated = conditions.translate_condition(decoded or [], self.options.segment_cohorts)
            if decoded is None or translated.skipped or translated.events:
                parts = list(translated.skipped) + [f"event {event['name']}" for event in translated.events]
                detail = f" `{'; '.join(parts)}`" if parts else ""
                self.note(
                    NoteLevel.NEEDS_INPUT,
                    f"Branch {index + 1}'s condition{detail} has no PostHog equivalent. Set it before enabling.",
                    base,
                )
            posthog_conditions.append(
                {"filters": {"properties": list(translated.properties)}, "name": f"Condition {index + 1}"}
            )
        # Customer.io puts the "no match" path last. PostHog takes the continue edge when nothing matches.
        links = self.links.get(str(source["id"]), [])
        new_links: list[tuple[str, str, int | None]] = []
        default_target = _EXIT_ID
        for target, _, edge_index in links:
            if edge_index is not None and edge_index < len(posthog_conditions):
                new_links.append((target, "branch", edge_index))
            else:
                default_target = target
        new_links.append((default_target, "continue", None))
        self.links[str(source["id"])] = new_links
        return {**base, "type": "conditional_branch", "config": {"conditions": posthog_conditions}}

    def _random_cohort(self, source: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        weights = [max(0, int(weight or 0)) for weight in source.get("cohorts") or []]
        names = list(source.get("cohort_names") or [])
        total = sum(weights) or 1
        percentages = [round(weight * 100 / total) for weight in weights]
        if percentages:
            # Rounding can leave the shares one off 100, so the largest group absorbs the difference.
            percentages[percentages.index(max(percentages))] += 100 - sum(percentages)
        cohorts = [
            {"percentage": percentage, **({"name": str(names[index])[:60]} if index < len(names) else {})}
            for index, percentage in enumerate(percentages)
        ]
        links = self.links.get(str(source["id"]), [])
        branch_links = [(target, "branch", index) for target, _, index in links if index is not None]
        last_target = max(branch_links, key=lambda link: link[2] or 0)[0] if branch_links else _EXIT_ID
        self.links[str(source["id"])] = [*branch_links, (last_target, "continue", None)]
        return {**base, "type": "random_cohort_branch", "config": {"cohorts": cohorts}}

    def _edges(self, roots: list[str]) -> list[dict[str, Any]]:
        def resolve(source_id: str) -> str:
            """The PostHog step a link to `source_id` lands on, following steps that were left out."""
            seen: set[str] = set()
            while source_id != _EXIT_ID and source_id not in self.actions:
                outgoing = self.links.get(source_id, [])
                if source_id in seen or not outgoing:
                    return _EXIT_ID
                seen.add(source_id)
                # A step that was left out passes people on along its default path: the continue edge, or the
                # last branch, which Customer.io uses for "everyone else".
                continue_links = [link for link in outgoing if link[1] == "continue"]
                source_id = (continue_links[0] if continue_links else max(outgoing, key=lambda link: link[2] or 0))[0]
            return _EXIT_ID if source_id == _EXIT_ID else self.actions[source_id]["id"]

        edges: list[dict[str, Any]] = []
        if roots:
            edges.append({"from": TRIGGER_ID, "to": resolve(roots[0]), "type": "continue"})
            if len(roots) > 1:
                self.note(NoteLevel.UNSUPPORTED, "The automation has steps that no path reaches. They were left out.")
        else:
            edges.append({"from": TRIGGER_ID, "to": _EXIT_ID, "type": "continue"})
        for source_id, action in self.actions.items():
            if action["type"] == "exit":
                continue
            outgoing = self.links.get(source_id, [])
            if not outgoing:
                outgoing = [(_EXIT_ID, "continue", None)]
            for target, edge_type, index in outgoing:
                edge: dict[str, Any] = {"from": action["id"], "to": resolve(target), "type": edge_type}
                if edge_type == "branch":
                    edge["index"] = index
                edges.append(edge)
        return edges


def translate_campaign(
    source: CampaignSource, options: ImportOptions, snippet_room: SnippetRoom | None = None
) -> TranslatedWorkflow:
    return _Builder(source, options, snippet_room or SnippetRoom()).build()


def _empty_trigger() -> dict[str, Any]:
    return {"type": "event", "filters": {"events": []}}


def _exit_action(action_id: str, name: str) -> dict[str, Any]:
    return {"id": action_id, "name": name, "description": "", "type": "exit", "config": {"reason": "Default exit"}}


def _duration(seconds: int) -> str:
    """A duration string for a number of seconds, within the workflow's per-unit limits: 2d, 1.5h, 45m, or 45s."""
    seconds = int(seconds)
    if seconds <= 0:
        return ""
    for unit, size, cap in _DURATION_UNITS:
        if seconds % size == 0 and (cap is None or seconds // size <= cap):
            return f"{seconds // size}{unit}"
    unit, size = next(
        (unit, size) for unit, size, cap in reversed(_DURATION_UNITS) if cap is None or seconds / size <= cap
    )
    return f"{seconds / size:.4f}".rstrip("0").rstrip(".") + unit


def _nodes(tree: Any, keys: tuple[str, ...] = ("and", "or", "not")) -> Iterator[dict[str, Any]]:
    """Every dict in a condition tree, parents before their children."""
    if isinstance(tree, list):
        for child in tree:
            yield from _nodes(child, keys)
    elif isinstance(tree, dict):
        yield tree
        for key in keys:
            if key in tree:
                yield from _nodes(tree[key], keys)


def _attribute_leaves(tree: Any) -> list[dict[str, Any]]:
    return [
        {**node["attribute"], "inverse": node["attribute"].get("inverse") or node.get("inverse")}
        for node in _nodes(tree)
        if isinstance(node.get("attribute"), dict)
    ]


def _segment_is_inverse(tree: Any) -> bool:
    return any(
        bool(node["segment"].get("inverse") or node.get("inverse"))
        for node in _nodes(tree)
        if isinstance(node.get("segment"), dict)
    )


def _foreign_event_leaves(tree: Any) -> list[dict[str, Any]]:
    return [
        node["foreign_event"]["attribute"]
        for node in _nodes(tree, ("and", "or"))
        if isinstance(node.get("foreign_event"), dict) and isinstance(node["foreign_event"].get("attribute"), dict)
    ]


def _segment_references(tree: Any) -> list[str]:
    found: list[str] = []
    for node in _nodes(tree):
        segment = node.get("segment")
        if isinstance(segment, dict) and segment.get("id") is not None:
            found.append(str(segment["id"]))
        if node.get("type") in ("segments_negatable", "segments"):
            found.extend(str(segment) for segment in node.get("segments") or [])
    return found


def _has_alternatives(tree: Any) -> bool:
    return any(isinstance(node.get("or"), list) and len(node["or"]) > 1 for node in _nodes(tree))


def _is_bare_event(tree: Any) -> bool:
    """True when the condition only names an event, with no property, segment or negated part."""
    if isinstance(tree, list):
        return all(_is_bare_event(child) for child in tree)
    if not isinstance(tree, dict):
        return False
    extra = [key for key, value in tree.items() if value and key not in ("and", "or", "event_name")]
    event_name = tree.get("event_name")
    if isinstance(event_name, dict) and any(value for key, value in event_name.items() if key != "name"):
        return False
    return not extra and all(_is_bare_event(tree[key]) for key in ("and", "or") if key in tree)


def _exit_event_names(tree: Any) -> list[str]:
    names: list[str] = []
    for node in _nodes(tree, ("and", "or")):
        event_name = node.get("event_name")
        if isinstance(event_name, dict) and event_name.get("name"):
            names.append(str(event_name["name"]))
        elif node.get("segment") is not None:
            names.append("__segment__")
    return names


@frozen
class _Address:
    email: str
    name: str


@frozen
class _Graph:
    actions: list[dict[str, Any]]
    edges: list[dict[str, Any]]


def _prune_unreachable(actions: list[dict[str, Any]], edges: list[dict[str, Any]]) -> _Graph:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge["from"], []).append(edge["to"])
    reachable: set[str] = set()
    queue = deque([TRIGGER_ID])
    while queue:
        node = queue.popleft()
        if node in reachable:
            continue
        reachable.add(node)
        queue.extend(adjacency.get(node, []))
    return _Graph(
        actions=[action for action in actions if action["id"] in reachable],
        edges=[edge for edge in edges if edge["from"] in reachable and edge["to"] in reachable],
    )


def _plain_name(name: Any) -> str:
    """A step name without Liquid, which the editor shows as raw `{{ ... }}`. Customer.io often names emails by subject."""
    text = _LIQUID_TAG.sub("", str(name or "")[:2000])
    text = re.sub(r"\s+([!?.,:;])", r"\1", re.sub(r"\s+", " ", text)).strip()
    return text[:400]


def _strip_comments(html: str) -> str:
    """Drop plain HTML comments, keeping Outlook's conditional ones (`<!--[if mso]>`, `<!--<![endif]-->`)."""
    parts: list[str] = []
    position = 0
    while (start := html.find("<!--", position)) != -1:
        end = html.find("-->", start + 4)
        if end == -1:
            break
        body = html[start + 4 : end]
        conditional = body.lstrip().startswith("[if") or "<![endif]" in body
        parts.append(html[position : end + 3] if conditional else html[position:start])
        position = end + 3
    parts.append(html[position:])
    return "".join(parts)


def _json_with_liquid(text: str) -> Any:
    """Parses a JSON body whose strings hold Liquid, like `"{{ customer.name | default: "" }}"`.

    Quotes inside a tag make the raw text invalid JSON, so each tag is swapped for a placeholder while parsing.
    Liquid outside a string still fails to parse.
    """
    try:
        return json.loads(text)
    except ValueError:
        pass
    # A random marker, so text in the body itself can never read as a placeholder.
    marker = f"liquid-{secrets.token_hex(8)}-"
    tags: dict[str, str] = {}

    def hold(match: re.Match[str]) -> str:
        key = f"{marker}{len(tags)}"
        tags[key] = match.group(0)
        return key

    parsed = json.loads(_LIQUID_TAG.sub(hold, text))
    placeholder = re.compile(re.escape(marker) + r"\d+")

    def restore(value: Any) -> Any:
        if isinstance(value, str):
            return placeholder.sub(lambda match: tags.get(match.group(0), match.group(0)), value)
        if isinstance(value, list):
            return [restore(item) for item in value]
        if isinstance(value, dict):
            return {restore(key): restore(item) for key, item in value.items()}
        return value

    return restore(parsed)
