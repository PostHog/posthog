import io
import re
import json
import base64
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from PIL import Image

from posthog.api.cohort import validate_filters_and_compute_realtime_support
from posthog.event_usage import EventSource
from posthog.models import User
from posthog.models.integration import Integration
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.uploaded_media import UploadedMedia
from posthog.models.utils import generate_random_token_personal

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.messaging.backend.facade.categories import create_category
from products.workflows.backend.facade.contracts import (
    CampaignSource,
    ImportCategory,
    ImportOptions,
    ImportSegment,
    ImportSender,
    SnippetRoom,
)
from products.workflows.backend.facade.enums import WorkflowImportNoteLevel as NoteLevel
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.presentation.views.data_suggestion_drafts import validated_draft
from products.workflows.backend.presentation.views.workflow_imports import CustomerioSegmentSerializer
from products.workflows.backend.services.customerio_import import conditions, liquid
from products.workflows.backend.services.customerio_import.images import _file_name
from products.workflows.backend.services.customerio_import.segments import segment_cohort_filters
from products.workflows.backend.services.customerio_import.translator import _json_with_liquid, translate_campaign


def _encode(condition: list[dict[str, Any]]) -> str:
    return base64.b64encode(quote(json.dumps(condition)).encode()).decode()


def _attribute_rule(attribute: dict[str, Any]) -> dict[str, Any]:
    check = {key: attribute[key] for key in ("operator", "value", "value2") if key in attribute}
    check.setdefault("operator", "eq")
    negated = bool(attribute.get("inverse"))
    return {
        "event": {
            "type": "attribute_change",
            "name": attribute["field"],
            "filters": {
                "and": [
                    {"field": "to", **check, "inverse": negated},
                    {"field": "from", **check, "inverse": not negated},
                ]
            },
        },
        "times": 1,
        "within": 0,
        "inverse": False,
    }


def _onboarding_campaign() -> CampaignSource:
    campaign = {
        "id": "42",
        "name": "Onboarding",
        "type": "transactional",
        "event": "signed_up",
        "event_type": "",
        "attribute_filters": {"and": [{"field": "plan", "operator": "eq", "value": "free"}]},
        "conversion": True,
        "conversion_type": "perform_event",
        "conversion_event_name": "subscribed",
        "conversion_window": 604800,
        "exit_on_conversion_matched": True,
        "workflow_action_ids": ["1", "2", "3", "4", "5", "6", "7", "8", "9"],
        "edges": [
            {"from": "1", "to": "2", "type": "continue"},
            {"from": "2", "to": "3", "type": "continue"},
            {"from": "3", "to": "4", "type": "continue"},
            {"from": "4", "to": "5", "type": "branch", "index": 0},
            {"from": "4", "to": "6", "type": "branch", "index": 1},
            {"from": "5", "to": "9", "type": "continue"},
            {"from": "6", "to": "7", "type": "branch", "index": 0},
            {"from": "6", "to": "8", "type": "branch", "index": 1},
            {"from": "7", "to": "9", "type": "continue"},
        ],
    }
    actions: list[dict[str, Any]] = [
        {"id": "1", "type": "email_action", "name": "Welcome", "template_id": "11"},
        {"id": "2", "type": "twilio_action", "name": "Welcome SMS"},
        {"id": "3", "type": "delay_seconds_action", "name": "Wait 2 days", "delay": 172800},
        {
            "id": "4",
            "type": "conditional_wait_action",
            "name": "Wait for activation",
            "exit_type": "continue",
            "delay": 259200,
            "multi_conditions": [_encode([{"type": "foreign_event", "event_name": "activated", "event_type": ""}])],
        },
        {"id": "5", "type": "email_action", "name": "Activated tips", "template_id": "12"},
        {
            "id": "6",
            "type": "conditional_branch_action",
            "name": "Has a company?",
            "conditions": _encode([{"type": "attribute", "field": "company", "operator": "exists"}]),
        },
        {"id": "7", "type": "email_action", "name": "Team nudge", "template_id": "13"},
        {"id": "8", "type": "exit_action"},
        {"id": "9", "type": "exit_action"},
    ]
    templates = {
        "11": {
            "id": 11,
            "subject": "Welcome, {{customer.first_name}}",
            "body": '<p>Hi {{ customer.first_name | default: "there" }}</p>{% snippet "footer" %}',
            "editor": "html",
        },
        "12": {"id": 12, "subject": "Nice work", "body": "<p>{{event.plan}}</p>", "editor": "html"},
        "13": {"id": 13, "subject": "Bring your team", "body": "<p>{{customer.company}}</p>", "editor": "html"},
    }
    return CampaignSource(campaign=campaign, actions=actions, templates=templates)


def _sync_templates() -> None:
    sync_template_to_db(MOCK_NODE_TEMPLATES[0])
    sync_template_to_db(
        {
            **MOCK_NODE_TEMPLATES[0],
            "id": "template-email",
            "name": "Email",
            "inputs_schema": [{"key": "email", "type": "native_email", "label": "Email", "required": True}],
        }
    )


_OPTIONS = ImportOptions(snippets={"footer": '<a href="{% unsubscribe_url %}">Unsubscribe</a>'}, segment_cohorts={})


class TestCustomerioCampaignTranslation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        _sync_templates()

    def test_translated_campaign_saves_as_a_draft_with_the_same_paths(self) -> None:
        translated = translate_campaign(_onboarding_campaign(), _OPTIONS)
        workflow = translated.workflow

        assert validated_draft(self.team, workflow, EventSource.API) is not None
        actions = {action["id"]: action for action in workflow["actions"]}
        assert workflow["trigger"]["filters"]["events"][0]["id"] == "signed_up"
        assert workflow["trigger"]["filters"]["events"][0]["properties"] == [
            {"key": "plan", "operator": "exact", "type": "event", "value": "free"}
        ]
        assert sorted(
            (edge["from"], edge["to"], edge["type"], edge.get("index")) for edge in workflow["edges"]
        ) == sorted(
            [
                ("trigger_node", "cio_1", "continue", None),
                # The SMS step is left out, so the welcome email leads straight to the delay.
                ("cio_1", "cio_3", "continue", None),
                ("cio_3", "cio_4", "continue", None),
                ("cio_4", "cio_5", "branch", 0),
                ("cio_4", "cio_6", "continue", None),
                ("cio_5", "cio_9", "continue", None),
                ("cio_6", "cio_7", "branch", 0),
                ("cio_6", "cio_8", "continue", None),
                ("cio_7", "cio_9", "continue", None),
            ]
        )
        assert actions["cio_3"]["config"] == {"delay_duration": "2d"}
        assert actions["cio_4"]["config"]["max_wait_duration"] == "3d"
        assert actions["cio_4"]["config"]["events"][0]["filters"]["events"][0]["id"] == "activated"
        assert actions["cio_6"]["config"]["conditions"][0]["filters"]["properties"] == [
            {"key": "company", "operator": "is_set", "type": "person"}
        ]
        email = actions["cio_1"]["config"]["inputs"]["email"]["value"]
        assert email["subject"] == "Welcome, {{person.properties.first_name}}"
        assert email["to"]["email"] == "{{person.properties.email}}"
        assert '<a href="{{ unsubscribe_url }}">Unsubscribe</a>' in email["html"]
        assert workflow["exit_condition"] == "exit_on_conversion"
        assert workflow["conversion"]["window"] == "7d"
        assert workflow["conversion"]["events"][0]["filters"]["events"][0]["id"] == "subscribed"
        assert any(note.level == NoteLevel.UNSUPPORTED and "SMS" in note.message for note in translated.notes)

    def test_values_the_workflow_checks_would_reject_are_reshaped(self) -> None:
        source = _onboarding_campaign()
        edges = [edge for edge in source.campaign["edges"] if edge["from"] != "5"]
        campaign = {
            **source.campaign,
            "workflow_action_ids": [*source.campaign["workflow_action_ids"], "10", "11", "12"],
            "exit_on_conversion_matched": False,
            "edges": [
                *edges,
                {"from": "5", "to": "10", "type": "continue"},
                {"from": "10", "to": "11", "type": "continue"},
                {"from": "11", "to": "12", "type": "continue"},
                {"from": "12", "to": "9", "type": "continue"},
            ],
            "conversion_event_filters": {
                "or": [
                    {"foreign_event": {"attribute": {"field": "plan", "operator": "eq", "value": "pro"}}},
                    {"foreign_event": {"attribute": {"field": "plan", "operator": "eq", "value": "team"}}},
                ]
            },
            "global_exit_conditions": [
                {"and": [{"event_name": {"name": "subscribed"}}, {"attribute": {"field": "plan", "value": "pro"}}]}
            ],
        }
        actions = [{**action, "delay": 129600} if action["id"] == "3" else action for action in source.actions] + [
            {"id": "10", "type": "attribute_update_action", "name": "Flags", "template_id": "14"},
            {"id": "11", "type": "webhook_action", "name": "CRM", "template_id": "15"},
            {
                "id": "12",
                "type": "create_event_action",
                "name": "Reminder sent",
                "template_id": "16",
                "event_name": json.dumps({"type": "static", "value": "reminder_sent"}),
            },
        ]
        templates = {
            **source.templates,
            "14": {"body": json.dumps([{"name": "active", "value": False}, {"name": "score", "value": 0}])},
            "15": {
                "url": "https://crm.example.com",
                "body": '{"name": "{{ customer.first_name | default: "" }}", "seats": 3}',
                "headers": [
                    {"name": "Authorization", "value": "Bearer fake-token"},
                    {"name": "X-Api-Key", "value": "{{customer.key}}"},
                    {"name": "X-Source", "value": "{{customer.id}}"},
                ],
            },
            "16": {
                "body": json.dumps(
                    [
                        {"name": "days_left", "type": "static", "value": "3"},
                        {"name": "plan", "type": "liquid", "value": "{{ customer.plan }}"},
                    ]
                )
            },
        }
        translated = translate_campaign(
            CampaignSource(campaign=campaign, actions=actions, templates=templates), _OPTIONS
        )
        workflow = translated.workflow
        steps = {action["id"]: action for action in workflow["actions"]}

        assert steps["cio_3"]["config"] == {"delay_duration": "1.5d"}
        assert steps["cio_10"]["config"]["inputs"]["set_properties"]["value"] == {"active": False, "score": 0}
        reminder = steps["cio_12"]["config"]["inputs"]
        assert reminder["event"]["value"] == "reminder_sent"
        assert reminder["properties"]["value"] == {"days_left": "3", "plan": "{{ person.properties.plan }}"}
        webhook = steps["cio_11"]["config"]["inputs"]
        assert webhook["headers"]["value"] == {"X-Source": "{{event.distinct_id}}"}
        assert webhook["secret_headers"]["value"] == {"Authorization": "Bearer fake-token"}
        assert webhook["body"]["value"] == {"name": '{{ person.properties.first_name | default: "" }}', "seats": 3}
        assert "properties" not in workflow["conversion"]["events"][0]["filters"]["events"][0]
        assert workflow["exit_condition"] == "exit_only_at_end"
        messages = [note.message for note in translated.notes]
        assert any("`X-Api-Key` header" in message for message in messages)
        assert any("any of several conditions" in message for message in messages)
        assert any("removes people from this automation" in message for message in messages)

    def test_goal_switched_on_without_an_event_is_left_out_quietly(self) -> None:
        source = _onboarding_campaign()
        campaign = {**source.campaign, "conversion_event_name": None}
        translated = translate_campaign(
            CampaignSource(campaign=campaign, actions=source.actions, templates=source.templates), _OPTIONS
        )

        assert translated.workflow["conversion"] is None
        assert not any("goal" in note.message for note in translated.notes)

    def test_long_chain_of_left_out_steps_resolves(self) -> None:
        source = _onboarding_campaign()
        ids = [str(index) for index in range(100, 1300)]
        actions = [{"id": step_id, "type": "twilio_action", "name": "SMS"} for step_id in ids] + [
            {"id": "99", "type": "exit_action"}
        ]
        edges = [{"from": a, "to": b, "type": "continue"} for a, b in zip(ids, [*ids[1:], "99"])]
        campaign = {**source.campaign, "workflow_action_ids": [*ids, "99"], "edges": edges}

        workflow = translate_campaign(
            CampaignSource(campaign=campaign, actions=actions, templates={}), _OPTIONS
        ).workflow

        assert {"from": "trigger_node", "to": "cio_99", "type": "continue"} in workflow["edges"]

    def test_draft_without_a_segment_cohort_or_webhook_content_still_saves_and_asks_for_them(self) -> None:
        source = _onboarding_campaign()
        campaign = {
            **source.campaign,
            "type": "seg_attr",
            "trigger": {"and": [{"or": [{"segment": {"id": 7}}]}]},
            "edges": [*source.campaign["edges"], {"from": "7", "to": "10", "type": "continue"}],
            "workflow_action_ids": [*source.campaign["workflow_action_ids"], "10"],
        }
        actions = [
            *source.actions,
            {"id": "10", "type": "webhook_action", "name": "CRM", "template_id": "15", "hostname": "crm.example.com"},
        ]
        translated = translate_campaign(
            CampaignSource(campaign=campaign, actions=actions, templates=source.templates), _OPTIONS
        )

        assert validated_draft(self.team, translated.workflow, EventSource.API) is not None
        assert any(note.level == NoteLevel.NEEDS_INPUT and "segment 7" in note.message for note in translated.notes)
        assert any(
            note.step_id == "cio_10"
            and "Set the webhook URL. Customer.io sends this request to crm.example.com." == note.message
            for note in translated.notes
        )

    def test_email_takes_its_layout_sender_and_category(self) -> None:
        source = _onboarding_campaign()
        campaign = {
            **source.campaign,
            "filters": _encode([{"type": "segments", "segments": [9]}]),
            "subscription_topic_id": "4",
        }
        actions = [
            {**action, "subscription_topic_id": 3, "name": "Welcome {{ customer.first_name }} !"}
            if action["id"] == "1"
            else {**action, "send_to_unsubscribed": True}
            if action["id"] == "7"
            else action
            for action in source.actions
        ]
        templates = {
            **source.templates,
            "11": {**source.templates["11"], "layout_id": 5, "from_identity_id": "77", "reply_to": "help@example.com"},
            "12": {**source.templates["12"], "from": "Ops <ops@example.com>", "layout_id": 6},
            "13": {
                **source.templates["13"],
                "subject": "Tips & tricks for {{ customer.company }}",
                "body": "<title>{{message.subject | default: ''}}</title><h1>{{ message.subject | upcase }}</h1>",
            },
        }
        options = ImportOptions(
            snippets={},
            segment_cohorts={},
            layouts={
                "5": "<html><body><!-- header --><!--[if mso]><table><![endif]-->{{ content }}"
                "<p>{{ customer.city }}</p><!--[if !mso]><!--><i>web</i><!--<![endif]--></body></html>"
            },
            sender_addresses={"77": "Team <team@example.com>"},
            senders={"team@example.com": ImportSender(integration_id=12, email="team@example.com", name="PostHog")},
            topic_categories={
                "3": ImportCategory(id="cat-1", category_type="marketing"),
                "4": ImportCategory(id="cat-2", category_type="marketing"),
            },
            segments={"9": ImportSegment(name="Beta list", type="static")},
        )
        translated = translate_campaign(
            CampaignSource(campaign=campaign, actions=actions, templates=templates), options
        )

        actions_by_id = {action["id"]: action for action in translated.workflow["actions"]}
        welcome = actions_by_id["cio_1"]["config"]
        email = welcome["inputs"]["email"]["value"]
        assert actions_by_id["cio_1"]["name"] == "Welcome!"
        assert email["html"].startswith(
            "<html><body><!--[if mso]><table><![endif]--><p>Hi {{ person.properties.first_name"
        )
        assert email["html"].endswith(
            "<p>{{ person.properties.city }}</p><!--[if !mso]><!--><i>web</i><!--<![endif]--></body></html>"
        )
        assert email["from"] == {"integrationId": 12, "email": "team@example.com", "name": "Team"}
        assert email["replyTo"] == "help@example.com"
        assert (welcome["message_category_id"], welcome["message_category_type"]) == ("cat-1", "marketing")
        assert actions_by_id["cio_5"]["config"]["message_category_id"] == "cat-2"
        nudge = actions_by_id["cio_7"]["config"]
        assert (nudge.get("message_category_id"), nudge["message_category_type"]) == (None, "transactional")
        nudge_html = nudge["inputs"]["email"]["value"]["html"]
        assert "<title>Tips &amp; tricks for {{ person.properties.company }}</title>" in nudge_html
        assert "<h1>{{ message.subject | upcase }}</h1>" in nudge_html
        activated = actions_by_id["cio_5"]["config"]["inputs"]["email"]["value"]
        assert activated["from"]["email"] == "ops@example.com"
        assert activated["html"].startswith('<div style="font-family: Arial, Helvetica, sans-serif;">')
        messages = [(note.level, note.step_id, note.message) for note in translated.notes]
        assert any(
            level == NoteLevel.NEEDS_INPUT and step == "cio_5" and "ops@example.com" in text
            for level, step, text in messages
        )
        assert any(
            level == NoteLevel.NEEDS_INPUT and step == "cio_5" and "layout 6" in text for level, step, text in messages
        )
        assert any(
            level == NoteLevel.NEEDS_INPUT and step is None and '"Beta list" (9) is a static list' in text
            for level, step, text in messages
        )
        assert any(text.startswith('Only people in segment "Beta list" (9) can enter') for _, _, text in messages)
        assert not any(step == "cio_1" and "sender" in text for _, step, text in messages)
        assert any(step == "cio_7" and "`message`" in text for _, step, text in messages)

    def test_language_split_keeps_only_the_default_message(self) -> None:
        campaign = {
            "id": "5",
            "name": "Localized",
            "type": "transactional",
            "event": "signed_up",
            "workflow_action_ids": ["1", "2", "3", "4"],
            "edges": [
                {"from": "1", "to": "2", "type": "branch", "index": 0},
                {"from": "1", "to": "3", "type": "branch", "index": 1},
                {"from": "2", "to": "4", "type": "continue"},
                {"from": "3", "to": "4", "type": "continue"},
            ],
        }
        actions: list[dict[str, Any]] = [
            {"id": "1", "type": "multi_lang_branch_action", "name": "Language", "multi_conditions": ["x"]},
            {"id": "2", "type": "email_action", "name": "Spanish", "template_id": "21"},
            {"id": "3", "type": "email_action", "name": "Default", "template_id": "22"},
            {"id": "4", "type": "exit_action"},
        ]
        templates = {"21": {"subject": "Hola", "body": "<p>Hola</p>"}, "22": {"subject": "Hi", "body": "<p>Hi</p>"}}
        translated = translate_campaign(
            CampaignSource(campaign=campaign, actions=actions, templates=templates), _OPTIONS
        )

        assert validated_draft(self.team, translated.workflow, EventSource.API) is not None
        assert [action["id"] for action in translated.workflow["actions"]] == ["trigger_node", "cio_3", "cio_4"]
        assert all(note.step_id != "cio_2" for note in translated.notes)


class TestCustomerioConditions(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "eq",
                {"type": "attribute", "field": "plan", "operator": "eq", "value": "pro"},
                [{"key": "plan", "operator": "exact", "type": "person", "value": "pro"}],
            ),
            (
                "negated",
                {"type": "attribute", "field": "plan", "operator": "!eq", "value": "pro"},
                [{"key": "plan", "operator": "is_not", "type": "person", "value": "pro"}],
            ),
            (
                "between",
                {"type": "event_attribute", "field": "amount", "operator": "bw", "value": "1", "value2": "9"},
                [
                    {"key": "amount", "operator": "gte", "type": "event", "value": "1"},
                    {"key": "amount", "operator": "lte", "type": "event", "value": "9"},
                ],
            ),
            (
                "relative date",
                {"type": "attribute", "field": "created_at", "operator": "timestamp_gt", "value": "-2592000"},
                [{"key": "created_at", "operator": "is_date_after", "type": "person", "value": "-30d"}],
            ),
            (
                "relative hours",
                {"type": "attribute", "field": "created_at", "operator": "timestamp_gt", "value": "-7200"},
                [{"key": "created_at", "operator": "is_date_after", "type": "person", "value": "-2h"}],
            ),
            (
                "absolute time of day",
                {"type": "attribute", "field": "created_at", "operator": "timestamp_lta", "value": "1700050000"},
                [
                    {
                        "key": "created_at",
                        "operator": "is_date_before",
                        "type": "person",
                        "value": "2023-11-15T12:06:40+00:00",
                    }
                ],
            ),
        ]
    )
    def test_translates_leaf_operators(
        self, _name: str, condition: dict[str, Any], expected: list[dict[str, Any]]
    ) -> None:
        assert conditions.translate_condition([condition], {}).properties == tuple(expected)

    @parameterized.expand(
        [
            ("message event", {"type": "message", "event": {"name": "*", "type": "opened_email"}, "inverse": False}),
            ("segment without a cohort", {"type": "segments_negatable", "segments": [3], "negate": False}),
            ("unknown operator", {"type": "attribute", "field": "plan", "operator": "matches", "value": "x"}),
            (
                "timestamp out of range",
                {"type": "attribute", "field": "created_at", "operator": "timestamp_gt", "value": "1700000000000000"},
            ),
        ]
    )
    def test_reports_conditions_it_cannot_translate(self, _name: str, condition: dict[str, Any]) -> None:
        translated = conditions.translate_condition([condition], {})
        assert translated.properties == ()
        assert len(translated.skipped) == 1

    def test_segment_attribute_rules_become_cohort_groups(self) -> None:
        rules = {
            "or": [
                _attribute_rule({"field": "plan", "operator": "eq", "value": "trial"}),
                {
                    "and": [
                        _attribute_rule({"field": "email", "operator": "exists"}),
                        {
                            **_attribute_rule({"field": "company", "operator": "contains", "value": "test"}),
                            "inverse": True,
                        },
                        _attribute_rule({"field": "seats", "operator": "bw", "value": "1", "value2": "9"}),
                    ]
                },
            ]
        }

        assert segment_cohort_filters(rules).filters == {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {"key": "plan", "operator": "regex", "type": "person", "value": "^[tT][rR][iI][aA][lL]$"}
                        ],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {"key": "email", "operator": "is_set", "type": "person", "value": "is_set"},
                            {"key": "company", "operator": "not_icontains", "type": "person", "value": "test"},
                            {"key": "seats", "operator": "gte", "type": "person", "value": "1"},
                            {"key": "seats", "operator": "lte", "type": "person", "value": "9"},
                        ],
                    },
                ],
            }
        }

    @parameterized.expand(
        [
            (
                "a change from one value to another",
                {
                    "and": [
                        {
                            "event": {
                                "type": "attribute_change",
                                "name": "plan",
                                "filters": {
                                    "and": [
                                        {"field": "to", "operator": "eq", "value": "trial", "inverse": False},
                                        {"field": "from", "operator": "eq", "value": "free", "inverse": False},
                                    ]
                                },
                            },
                            "times": 1,
                            "within": 0,
                        }
                    ]
                },
                ["plan changed to trial from free"],
            ),
            (
                "an attribute change within a time window",
                {"and": [{**_attribute_rule({"field": "plan", "value": "trial"}), "within": 604800}]},
                ["plan changed to trial"],
            ),
            (
                "an attribute check with no exact cohort operator",
                {"and": [_attribute_rule({"field": "plan", "operator": "one_of", "value": '["gold","silver"]'})]},
                ['plan one_of ["gold","silver"] (an unsupported operator)'],
            ),
            (
                "one translatable rule does not carry the segment",
                {
                    "and": [
                        _attribute_rule({"field": "plan", "operator": "eq", "value": "trial"}),
                        {"event": {"type": "event", "name": "signed_in"}, "times": 3, "within": 604800},
                    ]
                },
                ["performed signed_in at least 3 times within 7 days"],
            ),
            (
                "a relative date would keep people who aged out",
                {"and": [_attribute_rule({"field": "created_at", "operator": "timestamp_gt", "value": "-2592000"})]},
                ["created_at timestamp_gt -2592000 (a relative date)"],
            ),
            (
                "a range inside an any-of group",
                {"or": [_attribute_rule({"field": "seats", "operator": "bw", "value": "1", "value2": "9"})]},
                ["seats bw 1"],
            ),
            (
                "rules three levels deep",
                {"and": [{"or": [{"and": [_attribute_rule({"field": "plan", "value": "trial"})]}]}]},
                ["rules grouped more than two levels deep"],
            ),
            (
                "message activity",
                {"and": [{"message": {"type": "opened"}}]},
                ["message activity, such as opened or clicked"],
            ),
            (
                "an operator that is not a string",
                {"and": [_attribute_rule({"field": "plan", "operator": ["eq"], "value": "trial"})]},
                ["plan (an unsupported operator)"],
            ),
            ("no rules", {}, ["the segment has no rules"]),
            ("an empty group", {"and": []}, ["the segment has no rules"]),
            (
                "a negated group",
                {"and": [{"not": {"or": [_attribute_rule({"field": "plan", "value": "trial"})]}}]},
                ["a negated group of rules"],
            ),
        ]
    )
    def test_segment_with_any_untranslatable_rule_makes_no_cohort(
        self, _name: str, rules: dict[str, Any], untranslated: list[str]
    ) -> None:
        translated = segment_cohort_filters(rules)

        assert translated.filters is None
        assert list(translated.untranslated) == untranslated

    @parameterized.expand(
        [
            ("outer inverse", {**_attribute_rule({"field": "plan", "value": "trial"}), "inverse": True}, "not_regex"),
            ("inner inverse", _attribute_rule({"field": "plan", "value": "trial", "inverse": True}), "not_regex"),
            ("not wrapper", {"not": _attribute_rule({"field": "plan", "value": "trial"})}, "not_regex"),
            (
                "not wrapper around an inner inverse",
                {"not": _attribute_rule({"field": "plan", "value": "trial", "inverse": True})},
                "regex",
            ),
        ]
    )
    def test_negated_segment_rules_keep_their_audience(self, _name: str, rule: dict[str, Any], operator: str) -> None:
        filters = segment_cohort_filters({"and": [rule]}).filters

        assert filters is not None
        assert filters["properties"]["values"][0]["values"] == [
            {"key": "plan", "type": "person", "operator": operator, "value": "^[tT][rR][iI][aA][lL]$"}
        ]

    @parameterized.expand(
        [
            ("country code", "de", ["DE", "de", "De"], ["DEU", "d"]),
            ("accents and emoji", "zoë 🚀", ["Zoë 🚀", "ZOË 🚀"], ["Zoe 🚀"]),
            (
                "regex characters",
                "a.b+(c) #1 & ~x-y",
                ["A.B+(C) #1 & ~X-Y"],
                ["aXb+(c) #1 & ~x-y", "a.bb(c) #1 & ~x-y"],
            ),
        ]
    )
    def test_segment_values_match_without_case(
        self, _name: str, value: str, matching: list[str], not_matching: list[str]
    ) -> None:
        filters = segment_cohort_filters({"and": [_attribute_rule({"field": "country", "value": value})]}).filters

        assert filters is not None
        pattern = filters["properties"]["values"][0]["values"][0]["value"]
        assert [bool(re.search(pattern, candidate)) for candidate in matching + not_matching] == [True] * len(
            matching
        ) + [False] * len(not_matching)

    @parameterized.expand(
        [
            ("conditions that are not an object", {"conditions": ["plan"]}, "conditions"),
            ("conditions over the size limit", {"conditions": {"and": [{"x": "y" * 100_000}]}}, "conditions"),
            ("an id over 200 characters", {"id": "9" * 201}, "id"),
        ]
    )
    def test_rejects_malformed_segments(self, _name: str, change: dict[str, Any], field: str) -> None:
        segment = {"id": "16", "name": "Active trials", "type": "dynamic", **change}
        serializer = CustomerioSegmentSerializer(data=segment)

        assert not serializer.is_valid()
        assert list(serializer.errors) == [field]

    def test_decodes_url_encoded_and_plain_base64(self) -> None:
        condition = [{"type": "attribute", "field": "url", "operator": "eq", "value": "https://example.com/a%20b&c"}]
        plain = base64.b64encode(json.dumps(condition).encode()).decode()
        assert conditions.decode(_encode(condition)) == condition
        assert conditions.decode(plain) == condition


class TestCustomerioLiquid(SimpleTestCase):
    @parameterized.expand(
        [
            ("quotes_inside_liquid", '{"a": "{{ x | default: "" }}"}', {"a": '{{ x | default: "" }}'}),
            ("escaped_quotes_in_valid_json", '{"a": "{{ x | default: \\"\\" }}"}', {"a": '{{ x | default: "" }}'}),
            (
                "text_like_a_placeholder",
                '{"a": "liquid-0 \\ue0000\\ue001", "b": "{{ y | default: "" }}"}',
                {"a": "liquid-0 \ue0000\ue001", "b": '{{ y | default: "" }}'},
            ),
        ]
    )
    def test_webhook_body_keeps_its_liquid(self, _name: str, body: str, expected: dict[str, str]) -> None:
        assert _json_with_liquid(body) == expected

    @parameterized.expand(
        [
            ("customer attribute", "{{ customer.first_name }}", "{{ person.properties.first_name }}"),
            ("customer id", "{{customer.id}}", "{{event.distinct_id}}"),
            (
                "event attribute in a tag",
                "{% if event.plan == 'pro' %}x{% endif %}",
                "{% if event.properties.plan == 'pro' %}x{% endif %}",
            ),
            ("text outside tags", "customer.first_name", "customer.first_name"),
            (
                "bracket access",
                "{{ event['plan'] }}{{ trigger[\"x\"] }}",
                "{{ event.properties['plan'] }}{{ event.properties[\"x\"] }}",
            ),
            (
                "quoted literal",
                "{{ 'customer.email' | append: customer.email }}",
                "{{ 'customer.email' | append: person.properties.email }}",
            ),
            ("unsubscribe tag", '<a href="{% unsubscribe_url %}">', '<a href="{{ unsubscribe_url }}">'),
            (
                "captured html prints raw",
                "{% capture cta %}<b>Go</b>{% endcapture %}{{ cta }}{{- cta | strip -}}{{ cta | raw }}{{ other }}",
                "{% capture cta %}<b>Go</b>{% endcapture %}{{ cta | raw }}{{- cta | strip | raw -}}{{ cta | raw }}{{ other }}",
            ),
        ]
    )
    def test_rewrites_globals(self, _name: str, source: str, expected: str) -> None:
        assert liquid.rewrite(source, {}).text == expected

    def test_reports_globals_and_snippets_it_cannot_resolve(self) -> None:
        rewritten = liquid.rewrite('{{ journey.code }}{% snippet "legal" %}', {})
        assert rewritten.unsupported_globals == ("journey",)
        assert rewritten.missing_snippets == ("legal",)

    @parameterized.expand(
        [
            ("output_tag", "{{ snippets.big }}"),
            ("output_tag_with_brackets", '{{- snippets["big"] -}}'),
            ("legacy_tag", '{% snippet "big" %}'),
        ]
    )
    def test_stops_inlining_snippets_past_the_budget(self, _name: str, tag: str) -> None:
        room = SnippetRoom(remaining=10)
        rewritten = liquid.rewrite(tag * 3, {"big": "0123456"}, room)
        assert rewritten.text == "0123456" + tag * 2
        assert rewritten.missing_snippets == ("big",)

    def test_stops_inlining_the_subject_past_the_budget(self) -> None:
        source = _onboarding_campaign()
        templates = {**source.templates, "12": {**source.templates["12"], "body": "{{ message.subject }}" * 3}}
        translated = translate_campaign(
            CampaignSource(campaign=source.campaign, actions=source.actions, templates=templates),
            _OPTIONS,
            SnippetRoom(remaining=20),
        )

        steps = {action["id"]: action for action in translated.workflow["actions"]}
        assert "message.subject" in steps["cio_5"]["config"]["inputs"]["email"]["value"]["html"]
        assert any(note.step_id == "cio_5" and "`message`" in note.message for note in translated.notes)


class TestWorkflowImportAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _sync_templates()
        flag = patch("posthoganalytics.feature_enabled", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def test_import_needs_the_feature_flag(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self._post({"source": "customerio", "campaigns": [], "dry_run": False})

        assert response.status_code == 403
        assert response.json()["code"] == "feature_flag_required"

    def _post(self, body: dict[str, Any]) -> Any:
        return self.client.post(f"/api/projects/{self.team.id}/workflow_imports/", body, format="json")

    def _import(self, **overrides: Any) -> dict[str, Any]:
        source = _onboarding_campaign()
        body = {
            "source": "customerio",
            "campaigns": [
                {"campaign": source.campaign, "actions": source.actions, "templates": list(source.templates.values())}
            ],
            "snippets": {"footer": "<p>Footer</p>"},
            **overrides,
        }
        response = self._post(body)
        assert response.status_code == 200, response.json()
        return response.json()["results"][0]

    def test_reimport_updates_the_draft_until_it_is_enabled(self) -> None:
        first = self._import()
        preview = self._import(dry_run=True)
        second = self._import()

        assert (first["status"], preview["status"], second["status"]) == ("created", "preview", "updated")
        assert first["workflow_id"] == preview["workflow_id"] == second["workflow_id"]
        assert HogFlow.objects.filter(team=self.team).count() == 1

        HogFlow.objects.filter(pk=first["workflow_id"]).update(status="active")
        third = self._import()
        assert third["status"] == "skipped"
        assert HogFlow.objects.get(pk=first["workflow_id"]).status == "active"

    def test_segment_trigger_uses_the_mapped_realtime_cohort(self) -> None:
        cohort = Cohort.objects.create(
            team=self.team,
            name="Beta list",
            cohort_type=CohortType.REALTIME,
            last_backfill_person_properties_at=datetime(2026, 1, 1, tzinfo=UTC),
            last_backfill_events_at=datetime(2026, 1, 1, tzinfo=UTC),
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"key": "plan", "value": "pro", "type": "person", "operator": "exact"}],
                }
            },
        )
        source = _onboarding_campaign()
        campaign = {**source.campaign, "type": "seg_attr", "trigger": {"and": [{"segment": {"id": 7}}]}}
        rules = {"and": [_attribute_rule({"field": "plan", "operator": "eq", "value": "pro"})]}
        response = self._post(
            {
                "source": "customerio",
                "campaigns": [
                    {"campaign": campaign, "actions": source.actions, "templates": list(source.templates.values())}
                ],
                "segment_cohorts": {"7": cohort.id},
                "segments": [{"id": "7", "name": "Beta list", "type": "dynamic", "conditions": rules}],
            }
        )

        assert response.status_code == 200, response.json()
        result = response.json()["results"][0]
        assert result["status"] == "created", result["validation_errors"]
        trigger = HogFlow.objects.get(pk=result["workflow_id"]).trigger
        assert trigger["cohort_id"] == cohort.id
        assert response.json()["segment_cohorts"] == []
        assert self._imported_cohorts() == []

    def _segment_import(self, key: str | None = None, **overrides: Any) -> dict[str, Any]:
        source = _onboarding_campaign()
        segment_trigger = {
            **source.campaign,
            "id": "50",
            "type": "seg_attr",
            "trigger": {"and": [{"segment": {"id": 16}}]},
        }
        branch_on_segment = [
            {**action, "conditions": _encode([{"type": "segments", "segments": [16]}])}
            if action["id"] == "6"
            else action
            for action in source.actions
        ]
        templates = list(source.templates.values())
        body = {
            "source": "customerio",
            "campaigns": [
                {"campaign": segment_trigger, "actions": source.actions, "templates": templates},
                {"campaign": source.campaign, "actions": branch_on_segment, "templates": templates},
            ],
            "segments": [
                {
                    "id": "16",
                    "name": "Active trials",
                    "type": "dynamic",
                    "conditions": {"and": [_attribute_rule({"field": "plan", "operator": "eq", "value": "trial"})]},
                }
            ],
            **overrides,
        }
        headers = {"authorization": f"Bearer {key}"} if key else {}
        with self.settings(REALTIME_COHORT_TEAM_ALLOWLIST=str(self.team.id)):
            response = self.client.post(
                f"/api/projects/{self.team.id}/workflow_imports/", body, format="json", headers=headers
            )
        assert response.status_code == 200, response.json()
        return response.json()

    def _imported_cohorts(self) -> list[Cohort]:
        return list(Cohort.objects.filter(team=self.team, description__startswith="Imported from Customer.io"))

    def test_segment_rules_become_one_realtime_cohort_that_reimports_reuse(self) -> None:
        # Segment 1's cohort must not stand in for segment 16.
        Cohort.objects.create(team=self.team, name="Other", description="Imported from Customer.io segment 1.")

        preview = self._segment_import(dry_run=True)
        assert [item["status"] for item in preview["segment_cohorts"]] == ["would_create"]
        assert [result["status"] for result in preview["results"]] == ["preview", "preview"]
        assert len(self._imported_cohorts()) == 1
        preview_notes = [note["message"] for result in preview["results"] for note in result["notes"]]
        assert any("Importing for real creates the realtime cohort" in note for note in preview_notes)
        assert not any("Create a realtime cohort with these conditions" in note for note in preview_notes)

        first = self._segment_import()
        second = self._segment_import()

        cohort = Cohort.objects.get(team=self.team, description__startswith="Imported from Customer.io segment 16.")
        assert (cohort.name, cohort.cohort_type, cohort.is_static) == ("Active trials", CohortType.REALTIME, False)
        assert [(item["status"], item["cohort_id"]) for item in first["segment_cohorts"]] == [("created", cohort.id)]
        assert [(item["status"], item["cohort_id"]) for item in second["segment_cohorts"]] == [("reused", cohort.id)]
        assert len(self._imported_cohorts()) == 2
        trigger_flow, branch_flow = (HogFlow.objects.get(pk=result["workflow_id"]) for result in second["results"])
        assert trigger_flow.trigger == {"type": "cohort", "cohort_id": cohort.id, "transition": "entered"}
        branch = next(action for action in branch_flow.actions if action["type"] == "conditional_branch")
        assert {"key": "id", "type": "cohort", "operator": "in", "value": cohort.id} in branch["config"]["conditions"][
            0
        ]["filters"]["properties"]

        # A caller without cohort access must not learn a teammate's name for the cohort.
        Cohort.objects.filter(pk=cohort.pk).update(name="Renamed by a teammate")
        renamed = self._segment_import()
        Cohort.objects.filter(pk=cohort.pk).update(is_static=True)
        made_static = self._segment_import()

        assert [item["status"] for item in renamed["segment_cohorts"]] == ["reused"]
        assert [item["status"] for item in made_static["segment_cohorts"]] == ["not_converted"]
        notes = [note["message"] for run in (renamed, made_static) for r in run["results"] for note in r["notes"]]
        assert notes and not any("Renamed by a teammate" in note for note in notes)

        Cohort.objects.filter(pk=cohort.pk).update(deleted=True)
        after_delete = self._segment_import()

        assert [item["status"] for item in after_delete["segment_cohorts"]] == ["created"]
        assert after_delete["segment_cohorts"][0]["cohort_id"] not in (None, cohort.id)

    @parameterized.expand([("preview", True, "would_create"), ("import", False, "created")])
    def test_one_import_creates_at_most_the_cohort_budget(self, _name: str, dry_run: bool, first: str) -> None:
        source = _onboarding_campaign()
        templates = list(source.templates.values())
        rules = {"and": [_attribute_rule({"field": "plan", "operator": "eq", "value": "trial"})]}
        campaigns: list[dict[str, Any]] = [
            {
                "campaign": {
                    **source.campaign,
                    "id": f"5{segment}",
                    "type": "seg_attr",
                    "trigger": {"and": [{"segment": {"id": segment}}]},
                },
                "actions": source.actions,
                "templates": templates,
            }
            for segment in (16, 17)
        ]
        segments = [{"id": str(segment), "name": "", "type": "dynamic", "conditions": rules} for segment in (16, 17)]
        with patch(
            "products.workflows.backend.presentation.views.workflow_import_drafts.MAX_NEW_COHORTS_PER_IMPORT", 1
        ):
            response = self._segment_import(campaigns=campaigns, segments=segments, dry_run=dry_run)

        assert [item["status"] for item in response["segment_cohorts"]] == [first, "not_converted"]
        assert "creates at most 1 cohorts" in response["segment_cohorts"][1]["reason"]

    def test_segment_only_in_an_exit_condition_makes_no_cohort(self) -> None:
        source = _onboarding_campaign()
        campaign = {**source.campaign, "global_exit_conditions": {"and": [{"segment": {"id": 16}}]}}
        response = self._segment_import(
            campaigns=[{"campaign": campaign, "actions": source.actions, "templates": list(source.templates.values())}]
        )

        assert response["segment_cohorts"] == []
        assert self._imported_cohorts() == []

    @parameterized.expand(
        [
            ("eq", {"field": "plan", "operator": "eq", "value": "trial"}),
            ("not eq", {"field": "plan", "operator": "!eq", "value": "trial"}),
            ("contains", {"field": "email", "operator": "contains", "value": "@example.com"}),
            ("not contains", {"field": "email", "operator": "!contains", "value": "@example.com"}),
            ("greater than", {"field": "seats", "operator": "gt", "value": "5"}),
            ("less than", {"field": "seats", "operator": "lt", "value": "5"}),
            ("exists", {"field": "email", "operator": "exists"}),
            ("does not exist", {"field": "email", "operator": "!exists"}),
            ("between", {"field": "seats", "operator": "bw", "value": "1", "value2": "9"}),
            ("after a date", {"field": "created_at", "operator": "timestamp_gta", "value": "1767225600"}),
            ("before a date", {"field": "created_at", "operator": "timestamp_lta", "value": "1767225600"}),
            (
                "between dates",
                {"field": "created_at", "operator": "timestamp_bw", "value": "1767225600", "value2": "1769904000"},
            ),
        ]
    )
    def test_each_translated_operator_makes_a_realtime_cohort(self, _name: str, attribute: dict[str, Any]) -> None:
        filters = segment_cohort_filters({"and": [_attribute_rule(attribute)]}).filters
        assert filters is not None

        _, cohort_type, errors = validate_filters_and_compute_realtime_support(filters, self.team)
        assert (cohort_type, errors) == (CohortType.REALTIME, None)

    def test_segment_name_longer_than_a_cohort_name_is_cut(self) -> None:
        rules = {"and": [_attribute_rule({"field": "plan", "operator": "eq", "value": "trial"})]}
        segment = {"id": "16", "name": "x" * 450, "type": "dynamic", "conditions": rules}

        response = self._segment_import(segments=[segment])

        assert [item["status"] for item in response["segment_cohorts"]] == ["created"]
        assert [cohort.name for cohort in self._imported_cohorts()] == ["x" * 400]

    @parameterized.expand(
        [
            ("a rule with no cohort equivalent", {"untranslatable": True}, "plan changed"),
            ("an API key without the cohort scope", {"scopes": ["hog_flow:write"]}, "cohort:write"),
            ("a user without cohort access", {"cohort_access": False}, "edit access to cohorts"),
            ("a project without realtime cohorts", {"realtime": False}, "Realtime cohorts aren't available"),
            ("an organization without cohort triggers", {"cohort_triggers": False}, "Cohort triggers aren't available"),
        ]
    )
    def test_segment_that_cannot_become_a_cohort_keeps_the_note(
        self, _name: str, case: dict[str, Any], reason: str
    ) -> None:
        key = None
        if "scopes" in case:
            key = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="key", user=self.user, secure_value=hash_key_value(key), scopes=case["scopes"]
            )
            self.client.logout()
        overrides: dict[str, Any] = {}
        if case.get("untranslatable"):
            rules = {"and": [{"event": {"type": "attribute_change", "name": "plan"}, "times": 1, "within": 0}]}
            overrides["segments"] = [{"id": "16", "name": "Active trials", "type": "dynamic", "conditions": rules}]
        cohort_access = case.get("cohort_access", True)
        cohort_triggers = case.get("cohort_triggers", True)
        with (
            patch(
                "products.workflows.backend.presentation.views.workflow_import_drafts.UserAccessControl.check_access_level_for_resource",
                side_effect=lambda resource, *_args, **_kwargs: cohort_access or resource != "cohort",
            ),
            patch(
                "products.workflows.backend.presentation.views.workflow_import_drafts.realtime_cohorts_available",
                return_value=case.get("realtime", True),
            ),
            patch(
                "products.workflows.backend.presentation.views.workflow_import_drafts.cohort_conditions_rolled_out",
                return_value=cohort_triggers,
            ),
        ):
            response = self._segment_import(key=key, **overrides)

        assert [item["status"] for item in response["segment_cohorts"]] == ["not_converted"]
        assert reason in response["segment_cohorts"][0]["reason"]
        assert self._imported_cohorts() == []
        trigger_result = response["results"][0]
        assert trigger_result["status"] == "created", trigger_result["validation_errors"]
        assert any(reason in note["message"] for note in trigger_result["notes"])
        assert HogFlow.objects.get(pk=trigger_result["workflow_id"]).trigger["type"] == "event"

    def test_reimport_leaves_a_workflow_the_user_cannot_edit(self) -> None:
        first = self._import()
        with patch(
            "products.workflows.backend.presentation.views.workflow_import_drafts.UserAccessControl.check_access_level_for_ref",
            return_value=False,
        ):
            second = self._import()

        assert second["status"] == "skipped"
        assert second["workflow_id"] == first["workflow_id"]

    @parameterized.expand(
        [
            ("templates not a container", {"templates": "invalid"}),
            ("campaign id too long", {"campaign_id": "9" * 201}),
        ]
    )
    def test_rejects_malformed_campaigns_before_saving(self, _name: str, change: dict[str, Any]) -> None:
        source = _onboarding_campaign()
        campaign = {**source.campaign, "id": change.get("campaign_id", "42")}
        entry: dict[str, Any] = {"campaign": campaign, "actions": source.actions}
        if "templates" in change:
            entry["templates"] = change["templates"]
        body = {"source": "customerio", "campaigns": [entry]}
        response = self._post(body)

        assert response.status_code == 400
        assert not HogFlow.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("delay that is not a number", {"3": {"delay": "soon"}}, None, "failed"),
            (
                "message condition naming a plain event",
                {"4": {"multi_conditions": [_encode([{"type": "message", "event": "delivered"}])]}},
                None,
                "created",
            ),
            ("branch index that is not a number", {}, "x", "failed"),
            ("branch index as a string", {}, "1", "created"),
        ]
    )
    def test_an_odd_value_affects_only_that_automation(
        self, _name: str, action_changes: dict[str, dict[str, Any]], branch_index: str | None, status: str
    ) -> None:
        source = _onboarding_campaign()
        changed = [{**action, **action_changes.get(action["id"], {})} for action in source.actions]
        edges = [
            {**edge, "index": branch_index} if branch_index is not None and edge.get("index") == 1 else edge
            for edge in source.campaign["edges"]
        ]
        body = {
            "source": "customerio",
            "campaigns": [
                {"campaign": {**source.campaign, "edges": edges}, "actions": changed},
                {"campaign": {**source.campaign, "id": "43"}, "actions": source.actions},
            ],
        }
        response = self._post(body)

        assert response.status_code == 200, response.json()
        assert [result["status"] for result in response.json()["results"]] == [status, "created"]

    def test_dry_run_saves_nothing(self) -> None:
        result = self._import(dry_run=True)

        assert result["status"] == "preview"
        assert result["notes"]
        assert not HogFlow.objects.filter(team=self.team).exists()

    @patch("products.workflows.backend.services.customerio_import.app_api.time.sleep")
    @patch("products.workflows.backend.services.customerio_import.app_api.requests.Session.get")
    def test_reads_message_content_with_the_stored_key(self, mock_get: MagicMock, _sleep: MagicMock) -> None:
        Integration.objects.create(team=self.team, kind="customerio-app", sensitive_config={"app_api_key": "k"})
        create_category(self.team.id, None, {"key": "customerio_topic_3", "name": "Product news"})
        email_actions = [
            {
                "id": 1,
                "type": "email",
                "subject": "Hi",
                "body": "<p>Fetched {{customer.first_name}}</p>{{ snippets.signature }}",
                "from_id": 4,
            },
            {"id": 5, "type": "email", "subject": "Tips", "body": "<p>Tips</p>"},
        ]

        def respond(url: str, **kwargs: Any) -> MagicMock:
            response = MagicMock(status_code=200, headers={})
            if url.startswith("https://api.customer.io"):
                response.status_code = 401
            elif url.endswith("/campaigns/42/actions") and not kwargs["params"]:
                response.json.return_value = {"actions": email_actions[:1], "next": "page2"}
            elif url.endswith("/campaigns/42/actions"):
                response.json.return_value = {"actions": email_actions[1:], "next": ""}
            elif url.endswith("/sender_identities"):
                response.json.return_value = {"sender_identities": [{"id": 4, "email": "team@example.com"}]}
            elif url.endswith("/snippets"):
                response.json.return_value = {
                    "snippets": [{"name": "signature", "value": "<p>Bye {{customer.id}}</p>"}]
                }
            else:
                response.json.return_value = {}
            return response

        mock_get.side_effect = respond
        source = _onboarding_campaign()
        actions = [
            {**action, "subscription_topic_id": 3} if action["id"] == "1" else action for action in source.actions
        ]
        body = {"source": "customerio", "campaigns": [{"campaign": source.campaign, "actions": actions}]}
        response = self._post(body)

        assert response.status_code == 200, response.json()
        assert response.json()["content_fetched"] is True
        result = response.json()["results"][0]
        flow = HogFlow.objects.get(pk=result["workflow_id"])
        flow_actions = {action["id"]: action for action in flow.actions}
        welcome = flow_actions["cio_1"]["config"]
        assert welcome["inputs"]["email"]["value"]["html"] == (
            '<div style="font-family: Arial, Helvetica, sans-serif;"><p>Fetched {{person.properties.first_name}}</p>'
            "<p>Bye {{event.distinct_id}}</p></div>"
        )
        assert welcome["inputs"]["email"]["value"]["from"]["email"] == "team@example.com"
        assert welcome["message_category_type"] == "marketing"
        assert flow_actions["cio_5"]["config"]["inputs"]["email"]["value"]["subject"] == "Tips"
        # Template 13 has no App API action with its step's id, so it still asks for content.
        assert any(note["step_id"] == "cio_7" and "content" in note["message"] for note in result["notes"])
        assert all(call.kwargs["headers"]["Authorization"] == "Bearer k" for call in mock_get.call_args_list)

        HogFlow.objects.filter(pk=result["workflow_id"]).update(status="active")
        mock_get.reset_mock()
        assert self._post(body).json()["results"][0]["status"] == "skipped"
        assert not mock_get.called

    @patch("products.workflows.backend.services.customerio_import.app_api.time.sleep")
    @patch("products.workflows.backend.services.customerio_import.app_api.requests.Session.get")
    def test_rejected_key_still_imports_and_says_why(self, mock_get: MagicMock, _sleep: MagicMock) -> None:
        Integration.objects.create(team=self.team, kind="customerio-app", sensitive_config={"app_api_key": "k"})
        mock_get.return_value = MagicMock(status_code=401, headers={})
        source = _onboarding_campaign()
        body = {"source": "customerio", "campaigns": [{"campaign": source.campaign, "actions": source.actions}]}
        response = self._post(body)

        assert response.status_code == 200, response.json()
        assert response.json()["content_fetched"] is False
        result = response.json()["results"][0]
        assert result["status"] == "created", result["validation_errors"]
        assert any("could not read this automation's messages" in note["message"] for note in result["notes"])

    @patch("products.workflows.backend.services.customerio_import.images.requests.get")
    def test_copies_customerio_email_images_into_the_media_library(self, mock_get: MagicMock) -> None:
        png = io.BytesIO()
        Image.new("RGB", (3, 2)).save(png, "PNG")
        hero = "https://userimg-assets.customeriomail.com/images/client-env-1/hero.png"
        gone = "https://userimg-assets.customeriomail.com/images/client-env-1/gone.png"
        # A longer URL that starts with `hero`, and one whose query the HTML escapes.
        hero_webp, sized = f"{hero}.webp", f"{hero}?w=1&amp;h=2"
        logo = "https://userimg-assets.customeriomail.com/images/client-env-1/logo(1).png"
        # Neither may be requested: one only has an address at send time, one unescapes to another host.
        templated = "https://userimg-assets.customeriomail.com/images/client-env-1/v.png?v={{ person.properties.v }}"
        smuggled = "https://userimg-assets.customeriomail.com&#64;evil.example.com/a.png"
        lookalike = "https://userimg-assets.customeriomaİl.com/a.png"
        guide = "https://userimg-assets.customeriomail.com/files/client-env-1/guide.pdf"
        stalled = "https://userimg-assets.customeriomail.com/images/client-env-1/stalled.png"
        served = {hero, hero_webp, f"{hero}?w=1&h=2", logo}

        def respond(url: str, **kwargs: Any) -> MagicMock:
            response = MagicMock(status_code=200 if url in served or url == stalled else 404)
            response.__enter__.return_value = response
            response.raw = io.BytesIO(png.getvalue())
            if url == stalled:
                response.raw = MagicMock(spec=["read"], read=MagicMock(side_effect=TimeoutError("read timed out")))
            return response

        mock_get.side_effect = respond
        source = _onboarding_campaign()
        templates = {
            **source.templates,
            "11": {
                **source.templates["11"],
                "body": f'<img src="{hero}"><img src="{gone}"><img src="https://cdn.example.com/logo.png">'
                f'<img src="{hero_webp}"><img src="{sized}"><div style="background: url({logo})"></div>'
                f'<img src="{templated}"><img src="{smuggled}"><img src="{lookalike}">'
                f'<a href="{guide}">Guide</a><img src="{hero}?w=1&h=2"><img src="{stalled}">',
            },
        }
        campaigns = [{"campaign": source.campaign, "actions": source.actions, "templates": list(templates.values())}]

        preview = self._import(campaigns=campaigns, dry_run=True)
        assert any("6 email images on Customer.io's servers will be copied" in n["message"] for n in preview["notes"])
        assert not mock_get.called

        planted = UploadedMedia.objects.create(
            team=self.team,
            created_by=User.objects.create_and_join(self.organization, "other@example.com", None),
            purpose="email",
            file_name=_file_name(hero),
            media_location="planted/hero.png",
        )
        first = self._import(campaigns=campaigns)
        html = next(a for a in HogFlow.objects.get(pk=first["workflow_id"]).actions if a["id"] == "cio_1")["config"][
            "inputs"
        ]["email"]["value"]["html"]
        assert planted.get_absolute_url() not in html
        copies = list(
            UploadedMedia.objects.filter(team=self.team, purpose="email", created_by=self.user).order_by("created_at")
        )
        assert [(m.content_type, m.width, m.height) for m in copies] == [("image/png", 3, 2)] * 4
        urls = [media.get_absolute_url() for media in copies]
        assert html == (
            '<div style="font-family: Arial, Helvetica, sans-serif;">'
            f'<img src="{urls[0]}"><img src="{gone}"><img src="https://cdn.example.com/logo.png">'
            f'<img src="{urls[1]}"><img src="{urls[2]}"><div style="background: url({urls[3]})"></div>'
            f'<img src="{templated}"><img src="{smuggled}"><img src="{lookalike}">'
            f'<a href="{guide}">Guide</a><img src="{urls[2]}"><img src="{stalled}"></div>'
        )
        requested = [call.args[0] for call in mock_get.call_args_list]
        assert "evil.example.com" not in " ".join(requested)
        assert guide not in requested
        assert requested.count(f"{hero}?w=1&h=2") == 1
        assert any(n["step_id"] == "cio_1" and gone in n["message"] for n in first["notes"])
        design = json.dumps(
            next(a for a in HogFlow.objects.get(pk=first["workflow_id"]).actions if a["id"] == "cio_1")["config"][
                "inputs"
            ]["email"]["value"]["design"]
        )
        assert hero_webp not in design and urls[1] in design

        self._import(campaigns=campaigns)
        assert UploadedMedia.objects.filter(team=self.team, purpose="email", created_by=self.user).count() == 4
        assert [call.args[0] for call in mock_get.call_args_list].count(hero) == 1

        UploadedMedia.objects.filter(pk=copies[0].pk).update(archived_at=timezone.now())
        self._import(campaigns=campaigns)
        assert [call.args[0] for call in mock_get.call_args_list].count(hero) == 2
        assert (
            UploadedMedia.objects.filter(
                team=self.team, purpose="email", created_by=self.user, archived_at__isnull=True
            ).count()
            == 4
        )
        assert all(call.kwargs["allow_redirects"] is False for call in mock_get.call_args_list)

    @patch("products.workflows.backend.presentation.views.workflow_import_drafts._REQUEST_SECONDS", 0)
    @patch("products.workflows.backend.services.customerio_import.images.requests.get")
    def test_no_image_downloads_start_after_the_deadline(self, mock_get: MagicMock) -> None:
        source = _onboarding_campaign()
        image = "https://userimg-assets.customeriomail.com/images/client-env-1/late.png"
        templates = {**source.templates, "11": {**source.templates["11"], "body": f'<img src="{image}">'}}
        result = self._import(
            campaigns=[{"campaign": source.campaign, "actions": source.actions, "templates": list(templates.values())}]
        )

        assert result["status"] == "created"
        assert any(image in note["message"] for note in result["notes"])
        assert not mock_get.called

    @parameterized.expand(
        [
            ("an API key without the media scope", ["hog_flow:write"], True),
            ("a user without media access", ["*"], False),
        ]
    )
    @patch("products.workflows.backend.services.customerio_import.images.requests.get")
    def test_no_images_are_copied_without_media_access(
        self, _name: str, scopes: list[str], media_access: bool, mock_get: MagicMock
    ) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="key", user=self.user, secure_value=hash_key_value(key), scopes=scopes)
        self.client.logout()
        source = _onboarding_campaign()
        image = "https://userimg-assets.customeriomail.com/images/client-env-1/hero.png"
        templates = {**source.templates, "11": {**source.templates["11"], "body": f'<img src="{image}">'}}
        body = {
            "source": "customerio",
            "campaigns": [
                {"campaign": source.campaign, "actions": source.actions, "templates": list(templates.values())}
            ],
        }
        with patch(
            "products.workflows.backend.presentation.views.workflow_import_drafts.UserAccessControl.check_access_level_for_resource",
            side_effect=lambda resource, *_args, **_kwargs: media_access or resource != "uploaded_media",
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/workflow_imports/",
                body,
                format="json",
                headers={"authorization": f"Bearer {key}"},
            )

        assert response.status_code == 200, response.json()
        result = response.json()["results"][0]
        assert result["status"] == "created"
        assert any("media library" in note["message"] for note in result["notes"])
        assert not mock_get.called
        assert not UploadedMedia.objects.filter(team=self.team).exists()

    def test_notes_are_readable_by_workflow(self) -> None:
        result = self._import()

        url = f"/api/projects/{self.team.id}/workflow_imports/for_workflow/"
        response = self.client.get(url, {"hog_flow_id": result["workflow_id"]})
        assert response.status_code == 200
        assert response.json()["source_id"] == "42"
        assert response.json()["notes"] == result["notes"]

        other = HogFlow.objects.create(team=self.team, name="Built by hand")
        assert self.client.get(url, {"hog_flow_id": str(other.id)}).status_code == 204
