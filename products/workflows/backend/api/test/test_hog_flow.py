from datetime import UTC, datetime, timedelta
from typing import Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.event_usage import EventSource
from posthog.models import Organization, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.fixtures import create_app_metric2

from products.actions.backend.models.action import Action
from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.api.hog_flow import _should_validate_strictly
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job import HogFlowBatchJob

webhook_template = MOCK_NODE_TEMPLATES[0]


class TestHogFlowAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Create slack template in DB
        sync_template_to_db(template_slack)
        sync_template_to_db(webhook_template)

    def _create_hog_flow_with_action(self, action_config: dict):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": action_config,
        }

        hog_flow = {
            "name": "Test Flow",
            "actions": [trigger_action, action],
        }

        return hog_flow, action

    @patch("products.workflows.backend.api.hog_flow.publish_resource_edited")
    def test_emits_resource_edited_on_create_and_update(self, mock_emit):
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )

        create_response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        assert mock_emit.call_count == 1
        create_kwargs = mock_emit.call_args.kwargs
        assert create_kwargs["resource_type"] == "HogFlow"
        assert create_kwargs["resource_id"] == str(flow_id)
        assert create_kwargs["updated_at"]

        mock_emit.reset_mock()
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"name": "Renamed"},
        )
        assert update_response.status_code == 200, update_response.json()

        assert mock_emit.call_count == 1
        assert mock_emit.call_args.kwargs["resource_id"] == str(flow_id)

    def _create_simple_flow(self) -> str:
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        return response.json()["id"]

    def test_stale_update_is_rejected_with_409(self):
        flow_id = self._create_simple_flow()
        flow = HogFlow.objects.get(pk=flow_id)
        current = flow.updated_at.isoformat()
        stale = (flow.updated_at - timedelta(seconds=1)).isoformat()

        # A client that based its edit on an older copy is rejected rather than clobbering the newer one.
        stale_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"name": "Stale edit", "base_updated_at": stale},
        )
        assert stale_response.status_code == 409, stale_response.json()
        assert HogFlow.objects.get(pk=flow_id).name != "Stale edit"

        # A client whose base matches the current server copy proceeds.
        fresh_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"name": "Fresh edit", "base_updated_at": current},
        )
        assert fresh_response.status_code == 200, fresh_response.json()
        assert HogFlow.objects.get(pk=flow_id).name == "Fresh edit"

    def test_update_without_base_updated_at_is_not_gated(self):
        # Backwards compatible: callers that don't opt in to the base timestamp keep last-writer-wins.
        flow_id = self._create_simple_flow()
        flow = HogFlow.objects.get(pk=flow_id)
        stale = (flow.updated_at - timedelta(seconds=10)).isoformat()
        assert stale  # we hold a stale view but send no base

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"name": "Ungated edit"},
        )
        assert response.status_code == 200, response.json()
        assert HogFlow.objects.get(pk=flow_id).name == "Ungated edit"

    def test_timezone_naive_base_updated_at_is_handled(self):
        # A base_updated_at with no timezone designator parses naive; it must be coerced to aware
        # (assumed UTC) rather than raising TypeError when compared to the tz-aware stored updated_at.
        flow_id = self._create_simple_flow()
        flow = HogFlow.objects.get(pk=flow_id)
        naive = flow.updated_at.replace(tzinfo=None).isoformat()
        assert "+" not in naive and not naive.endswith("Z")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"name": "Naive base edit", "base_updated_at": naive},
        )
        assert response.status_code == 200, response.json()
        assert HogFlow.objects.get(pk=flow_id).name == "Naive base edit"

    def test_hog_flow_function_trigger_check(self):
        hog_flow = {
            "name": "Test Flow",
            "actions": [],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions",
            "code": "invalid_input",
            "detail": "Exactly one trigger action is required",
            "type": "validation_error",
        }

    def test_hog_flow_function_trigger_copied_from_action(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "webhook",
                "template_id": "template-webhook",
                "inputs": {
                    "url": {"value": "https://example.com"},
                },
            },
        }

        hog_flow = {
            "name": "Test Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        trigger_action_expectation = {
            "id": "trigger_node",
            "name": "trigger_1",
            "description": "",
            "on_error": None,
            "filters": None,
            "type": "trigger",
            "config": {
                "type": "webhook",
                "template_id": "template-webhook",
                "inputs": {
                    "url": {
                        "value": "https://example.com",
                        "bytecode": ["_H", 1, 32, "https://example.com"],
                        "order": 0,
                    }
                },
            },
            "output_variable": None,
        }

        assert response.status_code == 201, response.json()
        assert response.json()["actions"] == [trigger_action_expectation]
        assert response.json()["trigger"] == trigger_action_expectation["config"]

    def _make_delay_flow(self, delay_config: dict, status: Optional[str] = "active") -> dict:
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        delay_action = {"id": "d1", "name": "d1", "type": "delay", "config": delay_config}
        flow: dict = {"name": "Test Flow", "actions": [trigger_action, delay_action]}
        if status is not None:
            flow["status"] = status
        return flow

    @parameterized.expand(
        [
            ("missing_delay_duration", {}),
            ("null_delay_duration", {"delay_duration": None}),
            ("numeric_delay_duration", {"delay_duration": 1800}),
            ("seconds_as_input_shape", {"inputs": {"duration": {"value": 1800}}}),
            ("iso_8601_duration", {"delay_duration": "P30D"}),
            ("unit_and_duration_shape", {"unit": "days", "duration": 3}),
            ("unsupported_unit", {"delay_duration": "30s"}),
            ("empty_string", {"delay_duration": ""}),
        ]
    )
    def test_hog_flow_delay_validation_rejects_malformed_config(self, _name, bad_config):
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._make_delay_flow(bad_config))
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__config",
            "code": "invalid_input",
            "detail": (
                "delay_duration must be a string matching ^\\d*\\.?\\d+[dhm]$ "
                "(e.g. '30m', '2h', '1d'). ISO-8601 formats are not supported. "
                "For seconds, use a fraction of a minute."
            ),
            "type": "validation_error",
        }

    @parameterized.expand(
        [
            ("minutes", "30m"),
            ("hours", "2h"),
            ("days", "1d"),
            ("fractional", "1.5h"),
        ]
    )
    def test_hog_flow_delay_validation_accepts_canonical_config(self, _name, delay_duration):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            self._make_delay_flow({"delay_duration": delay_duration}),
        )
        assert response.status_code == 201, response.json()

    def test_hog_flow_delay_validation_lenient_for_drafts(self):
        # status omitted defaults to draft; draft mode lets users save WIP with invalid configs
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            self._make_delay_flow({"inputs": {"duration": {"value": 1800}}}, status=None),
        )
        assert response.status_code == 201, response.json()

    def test_hog_flow_function_validation(self):
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "missing",
                "inputs": {},
            }
        )
        hog_flow["status"] = "active"

        # Check that the template is found but missing required inputs
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__template_id",
            "code": "invalid_input",
            "detail": "Template not found",
            "type": "validation_error",
        }

        # Check that the template is found but missing required inputs
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {},
            }
        )
        hog_flow["status"] = "active"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__inputs__url",
            "code": "invalid_input",
            "detail": "This field is required.",
            "type": "validation_error",
        }

    def test_activating_draft_with_invalid_template_names_offending_step(self):
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                # Liquid-style syntax in a Hog-templated input: web drafts store it leniently,
                # so the compile error only surfaces on activation.
                "inputs": {"url": {"value": "{{ person.properties.email | upcase }}"}},
            }
        )
        action["name"] = "Send webhook"
        create_response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        # Status-only activation (the workflows list toggle) re-validates the stored actions
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
        assert response.status_code == 400, response.json()
        detail = response.json()["detail"]
        assert "Send webhook" in detail, response.json()
        assert "Invalid template" in detail, response.json()

    def test_hog_flow_bytecode_compilation(self):
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        hog_flow["status"] = "active"

        action["filters"] = {
            "properties": [{"key": "event", "type": "event_metadata", "value": ["custom_event"], "operator": "exact"}]
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        assert response.status_code == 201, response.json()
        hog_flow = HogFlow.objects.get(pk=response.json()["id"])

        assert hog_flow.trigger["filters"].get("bytecode") == ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]

        assert hog_flow.actions[1]["filters"].get("bytecode") == ["_H", 1, 32, "custom_event", 32, "event", 1, 1, 11]

        assert hog_flow.actions[1]["config"]["inputs"] == {
            "url": {"order": 0, "value": "https://example.com", "bytecode": ["_H", 1, 32, "https://example.com"]}
        }

    def test_hog_flow_conversion_filters_compiles_bytecode_on_create(self):
        expected_conversion_bytecode = [
            "_H",
            1,
            32,
            "Chrome",
            32,
            "$browser",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            11,
        ]

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        hog_flow["status"] = "active"
        hog_flow["conversion"] = {
            "filters": [
                {
                    "key": "$browser",
                    "type": "person",
                    "value": ["Chrome"],
                    "operator": "exact",
                }
            ],
            "window_minutes": None,
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        assert response.status_code == 201, response.json()
        conversion = response.json()["conversion"]
        assert conversion["filters"][0] == {
            "key": "$browser",
            "type": "person",
            "value": ["Chrome"],
            "operator": "exact",
        }
        assert conversion["bytecode"] == expected_conversion_bytecode

        flow = HogFlow.objects.get(pk=response.json()["id"])
        flow_conversion = flow.conversion
        assert flow_conversion is not None
        assert flow_conversion["window_minutes"] is None
        assert flow_conversion["filters"][0] == {
            "key": "$browser",
            "type": "person",
            "value": ["Chrome"],
            "operator": "exact",
        }
        assert flow_conversion["bytecode"] == expected_conversion_bytecode

    def test_hog_flow_conversion_event_object_in_filters_is_relocated(self):
        # A client (e.g. an LLM via MCP) that sends an event-based conversion goal as an object in
        # the property slot must not be rejected by the typed conversion field, nor persist the
        # malformed shape: it is relocated to conversion.events and compiled, and conversion.filters
        # is cleared. Mirrors the one-time backfill in migration 0009. Without the relocation the
        # object would fail array validation with a 400.
        event_obj = {
            "events": [{"id": "purchase", "name": "purchase", "type": "events", "order": 0}],
            "source": "events",
        }
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        hog_flow["status"] = "active"
        hog_flow["conversion"] = {"filters": event_obj, "window_minutes": None}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        conversion = response.json()["conversion"]
        assert conversion["filters"] == [], conversion
        assert len(conversion["events"]) == 1, conversion
        moved = conversion["events"][0]["filters"]
        assert moved["events"] == event_obj["events"]
        assert moved["bytecode"], moved
        assert "purchase" in moved["bytecode"]

    def test_hog_flow_conversion_client_supplied_bytecode_is_ignored(self):
        # Top-level conversion bytecode is read-only: the matcher executes it, so a client must not
        # be able to persist bytecode that didn't come from server-side compilation of filters.
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        hog_flow["status"] = "active"
        hog_flow["conversion"] = {"filters": [], "window_minutes": 60, "bytecode": ["_H", 1, 32, "injected"]}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        conversion = response.json()["conversion"]
        assert conversion["bytecode"] == [], conversion

    def test_hog_flow_conversion_filters_compiles_bytecode_on_update(self):
        expected_conversion_bytecode = [
            "_H",
            1,
            32,
            "Chrome",
            32,
            "$browser",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            11,
        ]

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        hog_flow["status"] = "active"

        create_response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {
                "conversion": {
                    "filters": [
                        {
                            "key": "$browser",
                            "type": "person",
                            "value": ["Chrome"],
                            "operator": "exact",
                        }
                    ],
                    "window_minutes": None,
                }
            },
        )

        assert update_response.status_code == 200, update_response.json()
        conversion = update_response.json()["conversion"]
        assert conversion["filters"][0] == {
            "key": "$browser",
            "type": "person",
            "value": ["Chrome"],
            "operator": "exact",
        }
        assert conversion["bytecode"] == expected_conversion_bytecode

        flow = HogFlow.objects.get(pk=flow_id)
        flow_conversion = flow.conversion
        assert flow_conversion is not None
        assert flow_conversion["window_minutes"] is None
        assert flow_conversion["filters"][0] == {
            "key": "$browser",
            "type": "person",
            "value": ["Chrome"],
            "operator": "exact",
        }
        assert flow_conversion["bytecode"] == expected_conversion_bytecode

    def test_hog_flow_conditional_branch_filters_bytecode(self):
        conditional_action = {
            "id": "cond_1",
            "name": "cond_1",
            "type": "function",
            "config": {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
                "conditions": [
                    {
                        "filters": {
                            "properties": [
                                {
                                    "key": "event",
                                    "type": "event_metadata",
                                    "value": ["custom_event"],
                                    "operator": "exact",
                                }
                            ]
                        }
                    }
                ],
            },
        }

        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        hog_flow = {
            "name": "Test Flow",
            "status": "active",
            "actions": [trigger_action, conditional_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        conditions = response.json()["actions"][1]["config"]["conditions"]
        assert "filters" in conditions[0]
        assert "bytecode" in conditions[0]["filters"], conditions[0]["filters"]
        assert conditions[0]["filters"]["bytecode"] == ["_H", 1, 32, "custom_event", 32, "event", 1, 1, 11]

    def test_hog_flow_wait_until_condition_defaults_missing_condition(self):
        # An events-only wait omits 'condition'; the FE always seeds it and StepWaitUntilCondition
        # assumes it, so the serializer defaults it to {filters: None} to keep one canonical shape.
        wait_action = {
            "id": "wait_1",
            "name": "wait_1",
            "type": "wait_until_condition",
            "config": {
                "events": [
                    {"filters": {"events": [{"id": "purchase", "name": "purchase", "type": "events", "order": 0}]}}
                ],
                "max_wait_duration": "1h",
            },
        }
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
            },
        }
        hog_flow = {"name": "Test Flow", "actions": [trigger_action, wait_action]}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        wait = next(a for a in response.json()["actions"] if a["type"] == "wait_until_condition")
        assert wait["config"]["condition"] == {"filters": None}, wait["config"]

    def test_hog_flow_conditional_branch_condition_missing_filters_rejected(self):
        # A bare {properties: [...]} (no 'filters' wrapper) compiles to always-false; reject it in strict mode.
        conditional_action = {
            "id": "cond_1",
            "name": "cond_1",
            "type": "conditional_branch",
            "config": {
                "conditions": [
                    {"properties": [{"key": "plan", "type": "person", "value": "enterprise", "operator": "exact"}]}
                ]
            },
        }
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
            },
        }
        hog_flow = {"name": "Test Flow", "status": "active", "actions": [trigger_action, conditional_action]}
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert "filters" in response.json()["detail"]

    def test_hog_flow_conditional_branch_missing_filters_allowed_for_web_draft(self):
        # Web-builder drafts stay lenient — an incomplete condition mid-edit must still save.
        conditional_action = {
            "id": "cond_1",
            "name": "cond_1",
            "type": "conditional_branch",
            "config": {"conditions": [{"properties": []}]},
        }
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
            },
        }
        # Default test client uses session auth → EventSource.WEB → lenient draft validation.
        hog_flow = {"name": "Test Flow", "status": "draft", "actions": [trigger_action, conditional_action]}
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

    def test_hog_flow_single_condition_field(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        wait_action = {
            "id": "wait_1",
            "name": "wait_1",
            "type": "wait_until_condition",
            "config": {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
                "condition": {
                    "filters": {
                        "properties": [
                            {
                                "key": "event",
                                "type": "event_metadata",
                                "value": ["custom_event"],
                                "operator": "exact",
                            }
                        ]
                    }
                },
            },
        }

        hog_flow = {
            "name": "Test Flow Single Condition",
            "status": "active",
            "actions": [trigger_action, wait_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        condition = response.json()["actions"][1]["config"]["condition"]
        assert "filters" in condition
        assert "bytecode" in condition["filters"], condition["filters"]
        assert condition["filters"]["bytecode"] == ["_H", 1, 32, "custom_event", 32, "event", 1, 1, 11]

    def test_hog_flow_condition_and_conditions_mutually_exclusive(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        wait_action = {
            "id": "wait_1",
            "name": "wait_1",
            "type": "wait_until_condition",
            "config": {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
                "condition": {
                    "filters": {
                        "properties": [
                            {
                                "key": "event",
                                "type": "event_metadata",
                                "value": ["custom_event"],
                                "operator": "exact",
                            }
                        ]
                    }
                },
                "conditions": [
                    {
                        "filters": {
                            "properties": [
                                {
                                    "key": "event",
                                    "type": "event_metadata",
                                    "value": ["another_event"],
                                    "operator": "exact",
                                }
                            ]
                        }
                    }
                ],
            },
        }

        hog_flow = {
            "name": "Test Flow Mutually Exclusive",
            "status": "active",
            "actions": [trigger_action, wait_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()

        data = response.json()
        assert data["attr"] == "actions__1__config"
        assert data["code"] == "invalid_input"
        assert data["type"] == "validation_error"

    def test_hog_flow_wait_until_events_filters_bytecode(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        wait_action = {
            "id": "wait_1",
            "name": "wait_1",
            "type": "wait_until_condition",
            "config": {
                "condition": {"filters": None},
                "max_wait_duration": "5m",
                "events": [
                    {
                        "filters": {
                            "events": [
                                {
                                    "id": "subscription created",
                                    "name": "subscription created",
                                    "type": "events",
                                    "order": 0,
                                    "properties": [
                                        {
                                            "key": "plan",
                                            "type": "event",
                                            "value": ["growth"],
                                            "operator": "exact",
                                        },
                                    ],
                                }
                            ],
                        },
                    },
                ],
            },
        }

        hog_flow = {
            "name": "Test Flow Wait Events Bytecode",
            "status": "active",
            "actions": [trigger_action, wait_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        events = response.json()["actions"][1]["config"]["events"]
        assert len(events) == 1
        filters = events[0]["filters"]
        assert "bytecode" in filters, filters
        bytecode = filters["bytecode"]
        assert "subscription created" in bytecode, bytecode
        assert "plan" in bytecode, bytecode
        assert "growth" in bytecode, bytecode

    def test_hog_flow_wait_until_drops_empty_events_entry(self):
        # An "events to wait for" entry that references no events compiles to always-true bytecode,
        # which would wake the job on every incoming event. It must be dropped on save; a real entry
        # alongside it is kept.
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        wait_action = {
            "id": "wait_1",
            "name": "wait_1",
            "type": "wait_until_condition",
            "config": {
                "condition": {
                    "filters": {
                        "properties": [{"key": "plan", "type": "person", "value": ["growth"], "operator": "exact"}],
                    },
                },
                "max_wait_duration": "5m",
                "events": [
                    {"filters": {"events": []}},
                    {
                        "filters": {
                            "events": [
                                {
                                    "id": "subscription created",
                                    "name": "subscription created",
                                    "type": "events",
                                    "order": 0,
                                }
                            ],
                        },
                    },
                ],
            },
        }

        hog_flow = {
            "name": "Test Flow Drop Empty Wait Events",
            "status": "active",
            "actions": [trigger_action, wait_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        events = response.json()["actions"][1]["config"]["events"]
        assert len(events) == 1, events
        assert "subscription created" in events[0]["filters"]["bytecode"], events[0]["filters"]

    def test_hog_flow_wait_until_keeps_action_only_entry(self):
        # An "events to wait for" entry can target a PostHog Action instead of an event: filters.actions
        # is set and filters.events is empty. That is a real wait and must be kept (and its bytecode
        # compiled), while a truly-empty entry alongside it is still dropped.
        action = Action.objects.create(team=self.team, name="Played with calculator", steps_json=[{"event": "calc"}])

        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
            },
        }
        wait_action = {
            "id": "wait_1",
            "name": "wait_1",
            "type": "wait_until_condition",
            "config": {
                "condition": {"filters": None},
                "max_wait_duration": "5m",
                "events": [
                    {"filters": {"events": []}},
                    {"filters": {"actions": [{"id": str(action.id), "type": "actions", "order": 0}], "events": []}},
                ],
            },
        }
        hog_flow = {
            "name": "Test Flow Keep Action Wait Entry",
            "status": "active",
            "actions": [trigger_action, wait_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        events = response.json()["actions"][1]["config"]["events"]
        assert len(events) == 1, events
        assert events[0]["filters"]["actions"] == [{"id": str(action.id), "type": "actions", "order": 0}]
        assert events[0]["filters"]["bytecode"], events[0]["filters"]

    def test_hog_flow_conversion_events_filters_bytecode(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        hog_flow = {
            "name": "Test Flow Conversion Events Bytecode",
            "status": "active",
            "actions": [trigger_action],
            "conversion": {
                "window_minutes": 60,
                "events": [
                    {
                        "filters": {
                            "events": [
                                {
                                    "id": "purchase completed",
                                    "name": "purchase completed",
                                    "type": "events",
                                    "order": 0,
                                    "properties": [
                                        {
                                            "key": "tier",
                                            "type": "event",
                                            "value": ["enterprise"],
                                            "operator": "exact",
                                        },
                                    ],
                                }
                            ],
                        },
                    },
                ],
            },
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        conversion_events = response.json()["conversion"]["events"]
        assert len(conversion_events) == 1
        filters = conversion_events[0]["filters"]
        assert "bytecode" in filters, filters
        bytecode = filters["bytecode"]
        assert "purchase completed" in bytecode, bytecode
        assert "tier" in bytecode, bytecode
        assert "enterprise" in bytecode, bytecode

    def test_hog_flow_conversion_drops_empty_keeps_action_event(self):
        # Same always-true guard as wait_until: a conversion "events" entry targeting nothing is
        # dropped (it would convert on every event), while an action-based entry is kept and compiled.
        action = Action.objects.create(team=self.team, name="Converted via action", steps_json=[{"event": "converted"}])
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
            },
        }
        hog_flow = {
            "name": "Test Flow Conversion Drop Empty Keep Action",
            "status": "active",
            "actions": [trigger_action],
            "conversion": {
                "window_minutes": 60,
                "events": [
                    {"filters": {"events": []}},
                    {"filters": {"actions": [{"id": str(action.id), "type": "actions", "order": 0}], "events": []}},
                ],
            },
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        conversion_events = response.json()["conversion"]["events"]
        assert len(conversion_events) == 1, conversion_events
        assert conversion_events[0]["filters"]["actions"] == [{"id": str(action.id), "type": "actions", "order": 0}]
        assert conversion_events[0]["filters"]["bytecode"], conversion_events[0]["filters"]

    def test_hog_flow_draft_conversion_event_strips_client_supplied_bytecode(self):
        # A draft with invalid conversion-event filters must not persist client-supplied
        # bytecode: conversion is not revalidated on a status-only activation, so it would
        # otherwise activate unvalidated and the matcher would execute it.
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        hog_flow = {
            "name": "Test Flow Draft Conversion Bytecode Injection",
            # No status => draft, so invalid filters are tolerated rather than rejected.
            "actions": [trigger_action],
            "conversion": {
                "window_minutes": 60,
                "events": [
                    {
                        "filters": {
                            # A real event target so the entry survives the empty-entry strip. The
                            # invalid source still fails serializer validation, so the draft branch
                            # keeps the raw filters - which must not retain the injected bytecode.
                            "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                            "source": "not-a-valid-source",
                            "bytecode": ["_H", 1, 32, "injected"],
                        },
                    },
                ],
            },
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        filters = response.json()["conversion"]["events"][0]["filters"]
        assert "bytecode" not in filters, filters

    def test_hog_flow_enable_disable(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        assert response.json()["status"] == "draft"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{response.json()['id']}", {"status": "active"}
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "active"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{response.json()['id']}", {"status": "draft"}
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "draft"

    def _create_active_hog_flow(self) -> str:
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create.status_code == 201, create.json()
        flow_id = create.json()["id"]
        activate = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
        assert activate.status_code == 200, activate.json()
        return flow_id

    def test_mcp_cannot_modify_active_workflow(self):
        # Active workflows are read-only via MCP for now — editing risks breaking already-scheduled runs.
        flow_id = self._create_active_hog_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"name": "Renamed via MCP"},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 400, response.json()
        assert "active workflow isn't supported via MCP" in response.json()["detail"]

    @parameterized.expand([("disable_to_draft", "draft"), ("archive", "archived")])
    def test_mcp_can_disable_active_workflow(self, _name, target_status):
        flow_id = self._create_active_hog_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": target_status},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == target_status

    def test_mcp_can_modify_draft_workflow(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create.status_code == 201, create.json()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{create.json()['id']}",
            {"name": "Renamed via MCP"},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 200, response.json()
        assert response.json()["name"] == "Renamed via MCP"

    def test_non_mcp_can_modify_active_workflow(self):
        flow_id = self._create_active_hog_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"name": "Renamed via UI"},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["name"] == "Renamed via UI"

    def test_mcp_cannot_create_active_workflow(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        hog_flow["status"] = "active"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow, HTTP_X_POSTHOG_CLIENT="mcp")
        assert response.status_code == 400, response.json()
        assert "one-shot active workflows via MCP" in response.json()["detail"]

    def test_mcp_can_create_draft_workflow(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow, HTTP_X_POSTHOG_CLIENT="mcp")
        assert response.status_code == 201, response.json()
        assert response.json()["status"] == "draft"

    def test_non_mcp_can_create_active_workflow(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        hog_flow["status"] = "active"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        assert response.json()["status"] == "active"

    def test_mcp_cannot_mix_status_with_other_field_updates(self):
        # Status changes must route through the lifecycle tools — a mixed status + field PATCH is rejected
        # (here on a draft, so it's the status-mixing guard rather than the active-workflow read-only guard).
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create.status_code == 201, create.json()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{create.json()['id']}",
            {"name": "Renamed", "status": "active"},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 400, response.json()
        assert "workflows-enable / workflows-disable / workflows-archive" in response.json()["detail"]

    def test_non_mcp_can_mix_status_with_other_field_updates(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create.status_code == 201, create.json()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{create.json()['id']}",
            {"name": "Renamed", "status": "active"},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "active"
        assert response.json()["name"] == "Renamed"

    def test_edges_validation_accepts_list_of_edges(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        hog_flow["edges"] = [{"from": "trigger_node", "to": "action_1", "type": "continue"}]
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        assert response.json()["edges"] == [{"from": "trigger_node", "to": "action_1", "type": "continue"}]

    def test_edges_validation_rejects_non_list(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        hog_flow["edges"] = "not-an-array"
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json()["attr"] == "edges"

    def _create_draft_flow_with_graph(self) -> str:
        # trigger -> action_1 (webhook) -> exit, created as a draft so the graph endpoint can edit it.
        trigger = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
            },
        }
        action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://old.example.com"}}},
        }
        exit_action = {"id": "exit_1", "name": "exit_1", "type": "exit", "config": {}}
        flow = {
            "name": "Test Flow",
            "status": "draft",
            "actions": [trigger, action, exit_action],
            "edges": [
                {"from": "trigger_node", "to": "action_1", "type": "continue"},
                {"from": "action_1", "to": "exit_1", "type": "continue"},
            ],
        }
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", flow)
        assert create.status_code == 201, create.json()
        return create.json()["id"]

    def _patch_graph(self, flow_id: str, operations: list[dict], **extra):
        return self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": operations},
            HTTP_X_POSTHOG_CLIENT="mcp",
            **extra,
        )

    def test_graph_update_action_changes_single_field(self):
        flow_id = self._create_draft_flow_with_graph()
        response = self._patch_graph(
            flow_id,
            [
                {
                    "op": "update_action",
                    "id": "action_1",
                    "patch": {"config": {"inputs": {"url": {"value": "https://new.example.com"}}}},
                }
            ],
        )
        assert response.status_code == 200, response.json()
        actions = {a["id"]: a for a in response.json()["actions"]}
        assert actions["action_1"]["config"]["inputs"]["url"]["value"] == "https://new.example.com"
        # The rest of the graph is intact.
        assert actions["trigger_node"]["type"] == "trigger"
        assert "exit_1" in actions

    @patch("products.workflows.backend.api.hog_flow.publish_resource_edited")
    def test_graph_update_emits_resource_edited(self, mock_emit):
        # The surgical /graph path is the primary MCP edit route, so it must emit the same
        # "edited elsewhere" signal as the full update path — otherwise an open builder never
        # learns about MCP graph edits and the cross-channel awareness has a hole.
        flow_id = self._create_draft_flow_with_graph()
        mock_emit.reset_mock()

        response = self._patch_graph(flow_id, [{"op": "update_action", "id": "action_1", "patch": {"name": "renamed"}}])
        assert response.status_code == 200, response.json()

        assert mock_emit.call_count == 1
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["resource_type"] == "HogFlow"
        assert kwargs["resource_id"] == str(flow_id)
        assert kwargs["updated_at"]

    def test_graph_response_echoes_full_graph(self):
        flow_id = self._create_draft_flow_with_graph()
        response = self._patch_graph(flow_id, [{"op": "update_action", "id": "action_1", "patch": {"name": "renamed"}}])
        assert response.status_code == 200, response.json()
        body = response.json()
        assert {"actions", "edges", "trigger"} <= set(body.keys())
        assert len(body["actions"]) == 3
        assert body["edges"] == [
            {"from": "trigger_node", "to": "action_1", "type": "continue"},
            {"from": "action_1", "to": "exit_1", "type": "continue"},
        ]

    def test_graph_remove_action_reconnects_edges(self):
        flow_id = self._create_draft_flow_with_graph()
        response = self._patch_graph(flow_id, [{"op": "remove_action", "id": "action_1"}])
        assert response.status_code == 200, response.json()
        body = response.json()
        assert sorted(a["id"] for a in body["actions"]) == ["exit_1", "trigger_node"]
        assert body["edges"] == [{"from": "trigger_node", "to": "exit_1", "type": "continue"}]

    def test_graph_dangling_edge_rejected_with_no_partial_write(self):
        flow_id = self._create_draft_flow_with_graph()
        response = self._patch_graph(
            flow_id, [{"op": "add_edge", "edge": {"from": "action_1", "to": "ghost", "type": "continue"}}]
        )
        assert response.status_code == 400, response.json()
        assert "unknown target action 'ghost'" in str(response.json())
        # Atomicity: the workflow's edges are unchanged on disk.
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.edges == [
            {"from": "trigger_node", "to": "action_1", "type": "continue"},
            {"from": "action_1", "to": "exit_1", "type": "continue"},
        ]

    def test_graph_empty_operations_rejected(self):
        flow_id = self._create_draft_flow_with_graph()
        response = self._patch_graph(flow_id, [])
        assert response.status_code == 400, response.json()

    def test_graph_mcp_cannot_edit_active_workflow(self):
        flow_id = self._create_active_hog_flow()
        response = self._patch_graph(flow_id, [{"op": "update_action", "id": "action_1", "patch": {"name": "x"}}])
        assert response.status_code == 400, response.json()
        assert "active workflow isn't supported via MCP" in response.json()["detail"]

    def test_graph_non_mcp_can_edit_active_workflow(self):
        flow_id = self._create_active_hog_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "update_action", "id": "action_1", "patch": {"name": "Renamed via UI"}}]},
        )
        assert response.status_code == 200, response.json()
        assert {a["id"]: a for a in response.json()["actions"]}["action_1"]["name"] == "Renamed via UI"

    def _flow_with_dangling_edge(self, status: str) -> dict:
        # A structurally-invalid graph: an edge pointing at an action that doesn't exist. Mirrors the
        # pre-existing corruption real workflows carry (stale edges from removed nodes/conditions).
        return {
            "name": "Dangling Flow",
            "status": status,
            "actions": [
                {
                    "id": "trigger_node",
                    "name": "t",
                    "type": "trigger",
                    "config": {
                        "type": "event",
                        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
                    },
                },
                {"id": "exit_1", "name": "exit", "type": "exit", "config": {}},
            ],
            "edges": [
                {"from": "trigger_node", "to": "exit_1", "type": "continue"},
                {"from": "trigger_node", "to": "ghost", "type": "continue"},
            ],
        }

    def test_create_active_flow_with_invalid_graph_is_lenient(self):
        # Option B: the full create/PATCH path no longer hard-blocks on graph structure — only the surgical
        # /graph endpoint enforces. A dangling edge is logged, not rejected, so callers (incl. the web UI on
        # an active save) aren't trapped by pre-existing corruption.
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._flow_with_dangling_edge("active"))
        assert response.status_code == 201, response.json()

    def test_full_patch_with_invalid_graph_is_lenient(self):
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._flow_with_dangling_edge("draft"))
        assert create.status_code == 201, create.json()
        flow_id = create.json()["id"]
        # Re-saving the (already structurally-broken) flow as active must succeed — the user isn't blocked
        # from editing a workflow whose graph corruption they didn't introduce.
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
        assert response.status_code == 200, response.json()
        assert HogFlow.objects.get(pk=flow_id).status == "active"

    def test_graph_endpoint_still_enforces_on_draft(self):
        # The new surgical endpoint is where corruption would be newly introduced, so it stays strict even
        # though the full-PATCH path is lenient.
        flow_id = self._create_draft_flow_with_graph()
        response = self._patch_graph(
            flow_id, [{"op": "add_edge", "edge": {"from": "action_1", "to": "ghost", "type": "continue"}}]
        )
        assert response.status_code == 400, response.json()
        assert "unknown target action 'ghost'" in str(response.json())

    def _graph_insert_events_only_wait_ops(self) -> list[dict]:
        # Splice an events-only wait_until_condition (no 'condition') between action_1 and exit_1, wiring
        # both its edges: a branch edge at index 0 (resolution) and a continue edge (the timeout path).
        return [
            {"op": "remove_edge", "edge": {"from": "action_1", "to": "exit_1", "type": "continue"}},
            {
                "op": "add_action",
                "action": {
                    "id": "wait_1",
                    "name": "Wait for purchase",
                    "type": "wait_until_condition",
                    "config": {
                        "events": [
                            {
                                "filters": {
                                    "events": [{"id": "purchase", "name": "purchase", "type": "events", "order": 0}]
                                }
                            }
                        ],
                        "max_wait_duration": "1h",
                    },
                },
            },
            {"op": "add_edge", "edge": {"from": "action_1", "to": "wait_1", "type": "continue"}},
            {"op": "add_edge", "edge": {"from": "wait_1", "to": "exit_1", "type": "branch", "index": 0}},
            {"op": "add_edge", "edge": {"from": "wait_1", "to": "exit_1", "type": "continue"}},
        ]

    def test_graph_events_only_wait_defaults_missing_condition(self):
        # The /graph patch path is becoming the main MCP edit route and routes through the same validate()
        # as create/update, so an events-only wait authored there must also get condition defaulted to
        # {filters: None} (otherwise the visual editor's StepWaitUntilCondition crashes on it).
        flow_id = self._create_draft_flow_with_graph()
        response = self._patch_graph(flow_id, self._graph_insert_events_only_wait_ops())
        assert response.status_code == 200, response.json()

        wait = next(a for a in response.json()["actions"] if a["type"] == "wait_until_condition")
        assert wait["config"]["condition"] == {"filters": None}, wait["config"]

    def test_graph_wait_without_index_0_branch_rejected(self):
        # A wait_until_condition wired with only a continue (timeout) edge silently never advances on
        # resolution; the surgical endpoint rejects it so the agent fixes the missing resolution edge.
        ops = [op for op in self._graph_insert_events_only_wait_ops() if op.get("edge", {}).get("type") != "branch"]
        flow_id = self._create_draft_flow_with_graph()
        response = self._patch_graph(flow_id, ops)
        assert response.status_code == 400, response.json()
        assert "missing its resolution edge" in str(response.json())

    def test_can_call_a_test_invocation(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create.status_code == 201, create.json()
        flow_id = create.json()["id"]

        with patch("products.workflows.backend.api.hog_flow.create_hog_flow_invocation_test") as mock_invoke:
            mock_invoke.return_value = MagicMock(status_code=200, json=lambda: {"status": "success"})

            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}/invocations/",
                data={
                    "globals": {"event": {"event": "$pageview", "distinct_id": "test-distinct-id"}},
                    "mock_async_functions": True,
                },
            )

            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json() == {"status": "success"}

            assert mock_invoke.call_count == 1
            assert mock_invoke.call_args.kwargs["team_id"] == self.team.id
            assert mock_invoke.call_args.kwargs["hog_flow_id"] == flow_id
            payload = mock_invoke.call_args.kwargs["payload"]
            assert payload["globals"] == {"event": {"event": "$pageview", "distinct_id": "test-distinct-id"}}
            assert payload["mock_async_functions"] is True

    def test_hog_flow_conditional_event_filter_rejected(self):
        conditional_action = {
            "id": "cond_1",
            "name": "cond_1",
            "type": "function",
            "config": {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
                "conditions": [
                    {
                        "filters": {
                            "events": [{"id": "custom_event", "name": "custom_event", "type": "events", "order": 0}]
                        }
                    }
                ],
            },
        }

        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        hog_flow = {
            "name": "Test Flow",
            "status": "active",
            "actions": [trigger_action, conditional_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__1__non_field_errors",
            "code": "invalid_input",
            "detail": "Event filters are not allowed in conditionals",
            "type": "validation_error",
        }

    def test_hog_flow_batch_trigger_valid_filters(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "batch",
                "filters": {
                    "properties": [{"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"}]
                },
            },
        }

        hog_flow = {
            "name": "Test Batch Flow",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        assert response.json()["trigger"]["type"] == "batch"
        assert response.json()["trigger"]["filters"]["properties"][0]["key"] == "email"

    def test_hog_flow_batch_trigger_without_filters(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "batch",
            },
        }

        hog_flow = {
            "name": "Test Batch Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()

    def test_hog_flow_batch_trigger_filters_not_dict(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "batch",
                "filters": "not a dict",
            },
        }

        hog_flow = {
            "name": "Test Batch Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__0__filters",
            "code": "invalid_input",
            "detail": "Filters must be a dictionary.",
            "type": "validation_error",
        }

    def test_hog_flow_batch_trigger_properties_not_array(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "batch",
                "filters": {
                    "properties": "not an array",
                },
            },
        }

        hog_flow = {
            "name": "Test Batch Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__0__filters__properties",
            "code": "invalid_input",
            "detail": "Properties must be an array.",
            "type": "validation_error",
        }

    def test_hog_flow_data_warehouse_table_trigger_valid(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "data-warehouse-table",
                "table_name": "postgres.table_1",
                "filters": {"properties": []},
            },
        }

        hog_flow = {
            "name": "Test DWH Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        trigger = response.json()["trigger"]
        assert trigger["type"] == "data-warehouse-table"
        assert trigger["table_name"] == "postgres.table_1"
        # Filters should be compiled to bytecode with the data-warehouse-table source
        assert trigger["filters"]["source"] == "data-warehouse-table"
        assert "bytecode" in trigger["filters"]

    def test_hog_flow_data_warehouse_table_trigger_without_table_name(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "data-warehouse-table",
                "filters": {"properties": []},
            },
        }

        hog_flow = {
            "name": "Test DWH Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__0__table_name",
            "code": "invalid_input",
            "detail": "A data warehouse table name is required for this trigger.",
            "type": "validation_error",
        }

    def test_hog_flow_data_warehouse_table_trigger_draft_allows_missing_table_name(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "data-warehouse-table",
                "filters": {"properties": []},
            },
        }

        hog_flow = {
            "name": "Test DWH Flow",
            "status": "draft",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

    def test_hog_flow_data_warehouse_table_trigger_filters_not_dict(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "data-warehouse-table",
                "table_name": "postgres.table_1",
                "filters": "not a dict",
            },
        }

        hog_flow = {
            "name": "Test DWH Flow",
            "status": "active",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": "actions__0__filters",
            "code": "invalid_input",
            "detail": "Filters must be a dictionary.",
            "type": "validation_error",
        }

    @parameterized.expand(
        [
            ("wait_until_condition", {"condition": {"filters": {"properties": []}}, "max_wait_duration": "5m"}),
            ("random_cohort_branch", {"cohorts": [{"percentage": 50}]}),
        ]
    )
    def test_hog_flow_data_warehouse_table_trigger_rejects_person_dependent_steps(self, action_type, action_config):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "data-warehouse-table",
                "table_name": "postgres.table_1",
                "filters": {"properties": []},
            },
        }
        person_dependent_action = {
            "id": "person_step",
            "name": "person_step",
            "type": action_type,
            "config": action_config,
        }

        hog_flow = {
            "name": "Test DWH Flow",
            "status": "active",
            "actions": [trigger_action, person_dependent_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert response.json()["attr"] == "actions"
        assert action_type in response.json()["detail"]

    def test_hog_flow_data_warehouse_table_trigger_draft_allows_person_dependent_steps(self):
        # Drafts are not executed, so we defer the hard rejection until activation.
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "data-warehouse-table",
                "table_name": "postgres.table_1",
                "filters": {"properties": []},
            },
        }
        person_dependent_action = {
            "id": "person_step",
            "name": "person_step",
            "type": "random_cohort_branch",
            "config": {"cohorts": [{"percentage": 50}]},
        }

        hog_flow = {
            "name": "Test DWH Flow",
            "status": "draft",
            "actions": [trigger_action, person_dependent_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

    def test_hog_flow_data_warehouse_table_trigger_forces_exit_only_at_end(self):
        # Other exit conditions re-evaluate trigger/conversion filters that may reference person
        # data, so warehouse-triggered flows are coerced to exit_only_at_end regardless of input.
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "data-warehouse-table",
                "table_name": "postgres.table_1",
                "filters": {"properties": []},
            },
        }

        hog_flow = {
            "name": "Test DWH Flow",
            "status": "active",
            "exit_condition": "exit_on_conversion",
            "actions": [trigger_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        assert response.json()["exit_condition"] == "exit_only_at_end"

    @parameterized.expand(
        [
            ("events", {"events": [{"id": "$pageview", "type": "events"}]}),
            ("actions", {"actions": [{"id": "5", "type": "actions"}]}),
        ]
    )
    def test_hog_flow_batch_trigger_rejects_event_behavior_filters(self, _name, extra_filters):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {"type": "batch", "filters": {"properties": [], **extra_filters}},
        }
        hog_flow = {"name": "Test Batch Flow", "status": "active", "actions": [trigger_action]}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()
        assert "event" in response.json()["detail"].lower()

    def test_hog_flow_batch_trigger_event_filters_rejected_for_mcp_draft(self):
        # Same draft discriminator as behavioral cohorts: enforced for programmatic callers, lenient for the UI.
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "batch",
                "filters": {"properties": [], "events": [{"id": "$pageview", "type": "events"}]},
            },
        }
        hog_flow = {"name": "Test Batch Flow", "status": "draft", "actions": [trigger_action]}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow, HTTP_X_POSTHOG_CLIENT="mcp")
        assert response.status_code == 400, response.json()
        assert "event" in response.json()["detail"].lower()

    def test_hog_flow_batch_trigger_allows_empty_properties_audience(self):
        # Empty properties = broadcast to everyone, a legitimate batch audience — must not be rejected.
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "batch",
                "filters": {"properties": []},
            },
        }
        hog_flow = {"name": "Test Batch Flow", "status": "active", "actions": [trigger_action]}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

    def _make_cohort(self, *, behavioral=False, static=False, nested_cohort_id=None) -> Cohort:
        if behavioral:
            properties = {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "time_value": 30,
                                "time_interval": "day",
                            }
                        ],
                    }
                ],
            }
        elif nested_cohort_id is not None:
            properties = {
                "type": "OR",
                "values": [{"type": "OR", "values": [{"key": "id", "type": "cohort", "value": nested_cohort_id}]}],
            }
        else:  # property-based dynamic
            properties = {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [{"key": "email", "type": "person", "value": "a@b.com", "operator": "exact"}],
                    }
                ],
            }
        # A static cohort keeps its original filter definition (behavioral/property/nested) even though
        # membership is frozen — only a plain static cohort with no source criteria has empty filters.
        if static and not (behavioral or nested_cohort_id is not None):
            filters = {}
        else:
            filters = {"properties": properties}
        return Cohort.objects.create(team=self.team, name="c", filters=filters, is_static=static)

    def _post_batch_with_cohort(self, cohort_id: int, *, status: str = "active", trigger_type: str = "batch", **extra):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": trigger_type,
                "filters": {"properties": [{"key": "id", "type": "cohort", "value": cohort_id, "operator": "in"}]},
            },
        }
        hog_flow = {"name": "Test Batch Flow", "status": status, "actions": [trigger_action]}
        return self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow, **extra)

    @parameterized.expand(["batch", "schedule"])
    def test_hog_flow_audience_rejects_behavioral_cohort(self, trigger_type: str):
        cohort = self._make_cohort(behavioral=True)
        response = self._post_batch_with_cohort(cohort.pk, trigger_type=trigger_type)
        assert response.status_code == 400, response.json()
        assert "behavior" in response.json()["detail"].lower()

    def test_hog_flow_batch_trigger_rejects_nested_behavioral_cohort(self):
        behavioral = self._make_cohort(behavioral=True)
        wrapper = self._make_cohort(nested_cohort_id=behavioral.pk)
        response = self._post_batch_with_cohort(wrapper.pk)
        assert response.status_code == 400, response.json()
        assert "behavior" in response.json()["detail"].lower()

    @parameterized.expand([("static", {"static": True}), ("property-based", {})])
    def test_hog_flow_batch_trigger_allows_non_behavioral_cohort(self, _name, cohort_kwargs):
        cohort = self._make_cohort(**cohort_kwargs)
        response = self._post_batch_with_cohort(cohort.pk)
        assert response.status_code == 201, response.json()

    @parameterized.expand(["batch", "schedule"])
    def test_hog_flow_audience_allows_behavioral_static_cohort(self, trigger_type: str):
        # A static cohort built from behavioral criteria keeps its behavioral filter definition, but its
        # membership is frozen and precalculated, so it's a valid audience — the error even recommends it.
        cohort = self._make_cohort(behavioral=True, static=True)
        response = self._post_batch_with_cohort(cohort.pk, trigger_type=trigger_type)
        assert response.status_code == 201, response.json()

    def test_hog_flow_batch_trigger_allows_wrapper_of_static_behavioral_cohort(self):
        behavioral_static = self._make_cohort(behavioral=True, static=True)
        wrapper = self._make_cohort(nested_cohort_id=behavioral_static.pk)
        response = self._post_batch_with_cohort(wrapper.pk)
        assert response.status_code == 201, response.json()

    def test_hog_flow_batch_trigger_behavioral_cohort_rejected_for_mcp_draft(self):
        # Draft is lenient for the UI builder but enforced for programmatic (MCP) callers.
        cohort = self._make_cohort(behavioral=True)
        response = self._post_batch_with_cohort(cohort.pk, status="draft", HTTP_X_POSTHOG_CLIENT="mcp")
        assert response.status_code == 400, response.json()
        assert "behavior" in response.json()["detail"].lower()

    def test_hog_flow_batch_trigger_behavioral_cohort_allowed_for_web_draft(self):
        # Web UI must be able to save incomplete draft graphs without the guard firing.
        cohort = self._make_cohort(behavioral=True)
        response = self._post_batch_with_cohort(cohort.pk, status="draft")
        assert response.status_code == 201, response.json()

    def _post_event_trigger_with_cohort(self, cohort_id: int, *, status: str = "draft", **extra):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                    "properties": [{"key": "id", "type": "cohort", "value": cohort_id, "operator": "in"}],
                },
            },
        }
        hog_flow = {"name": "Test Event Flow", "status": status, "actions": [trigger_action]}
        return self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow, **extra)

    def test_hog_flow_event_trigger_cohort_filter_rejected_for_mcp_draft(self):
        # Cohorts can't be evaluated in real-time event filters. Generalized strict validation rejects this
        # at create for programmatic callers, instead of silently storing a filter that won't compile and
        # only surfacing the failure at enable (which reads to the caller as a successful create).
        cohort = self._make_cohort(behavioral=True)
        response = self._post_event_trigger_with_cohort(cohort.pk, HTTP_X_POSTHOG_CLIENT="mcp")
        assert response.status_code == 400, response.json()
        assert "cohort" in str(response.json()).lower()

    def test_hog_flow_event_trigger_cohort_filter_allowed_for_web_draft(self):
        # Web builder drafts stay lenient so incomplete graphs can be saved mid-edit.
        cohort = self._make_cohort(behavioral=True)
        response = self._post_event_trigger_with_cohort(cohort.pk)
        assert response.status_code == 201, response.json()

    @parameterized.expand(
        [
            # (name, is_draft, event_source, expected_strict)
            ("active_no_source", False, None, True),
            ("active_web", False, EventSource.WEB, True),
            ("draft_no_source", True, None, False),  # internal re-saves (e.g. refresh command) stay lenient
            ("draft_web", True, EventSource.WEB, False),
            ("draft_mcp", True, EventSource.MCP, True),
            ("draft_api", True, EventSource.API, True),
        ]
    )
    def test_should_validate_strictly(self, _name, is_draft, event_source, expected_strict):
        context = {} if event_source is None else {"event_source": event_source}
        assert _should_validate_strictly(context, is_draft) is expected_strict

    def test_hog_flow_user_blast_radius_requires_filters(self):
        with patch("products.workflows.backend.api.hog_flow.get_user_blast_radius") as mock_get_user_blast_radius:
            response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/user_blast_radius", {})

        assert response.status_code == 400, response.json()
        assert "Missing filters" in response.json().get("detail", "")
        mock_get_user_blast_radius.assert_not_called()

    def test_hog_flow_user_blast_radius_returns_counts(self):
        with patch("products.workflows.backend.api.hog_flow.get_user_blast_radius") as mock_get_user_blast_radius:
            from products.feature_flags.backend.user_blast_radius import BlastRadiusResult  # noqa: PLC0415

            mock_get_user_blast_radius.return_value = BlastRadiusResult(affected=4, total=10)

            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/user_blast_radius",
                {"filters": {"properties": []}},
            )

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["affected"] == 4
        assert body["total"] == 10
        assert "limit" in body
        assert body["limit"] > 0

    @override_settings(
        HOGFLOW_BATCH_TRIGGER_LIMIT=5000,
        HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=50000,
        HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS=set(),
    )
    def test_hog_flow_user_blast_radius_returns_default_limit_for_unlisted_team(self):
        with patch("products.workflows.backend.api.hog_flow.get_user_blast_radius") as mock_get_user_blast_radius:
            from products.feature_flags.backend.user_blast_radius import BlastRadiusResult  # noqa: PLC0415

            mock_get_user_blast_radius.return_value = BlastRadiusResult(affected=0, total=0)
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/user_blast_radius",
                {"filters": {"properties": []}},
            )

        assert response.status_code == 200, response.json()
        assert response.json()["limit"] == 5000

    def test_hog_flow_user_blast_radius_returns_elevated_limit_for_listed_team(self):
        with (
            override_settings(
                HOGFLOW_BATCH_TRIGGER_LIMIT=5000,
                HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=50000,
                HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS={self.team.id},
            ),
            patch("products.workflows.backend.api.hog_flow.get_user_blast_radius") as mock_get_user_blast_radius,
        ):
            from products.feature_flags.backend.user_blast_radius import BlastRadiusResult  # noqa: PLC0415

            mock_get_user_blast_radius.return_value = BlastRadiusResult(affected=0, total=0)
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/user_blast_radius",
                {"filters": {"properties": []}},
            )

        assert response.status_code == 200, response.json()
        assert response.json()["limit"] == 50000

    def test_user_blast_radius_personal_api_key_requires_person_read_scope(self):
        # Sizing an audience queries person data, so a hog_flow:read-only token must NOT be able to use
        # this as a person-count oracle — person:read is also required.
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="hog_flow only", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:read"]
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/user_blast_radius",
            {"filters": {"properties": []}},
            headers={"authorization": f"Bearer {key}"},
        )
        assert response.status_code == 403, response.json()
        assert "person:read" in response.json().get("detail", "")

    def test_user_blast_radius_personal_api_key_with_person_read_scope_allowed(self):
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="hog_flow + person",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=["hog_flow:read", "person:read"],
        )
        with patch("products.workflows.backend.api.hog_flow.get_user_blast_radius") as mock_get_user_blast_radius:
            from products.feature_flags.backend.user_blast_radius import BlastRadiusResult  # noqa: PLC0415

            mock_get_user_blast_radius.return_value = BlastRadiusResult(affected=1, total=10)
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/user_blast_radius",
                {"filters": {"properties": []}},
                headers={"authorization": f"Bearer {key}"},
            )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["affected"] == 1
        assert body["total"] == 10
        assert "limit" in body

    @parameterized.expand(
        [
            ("flag_only", [{"key": "my-other-flag", "type": "flag", "value": "true", "operator": "exact"}]),
            (
                "flag_mixed_with_person",
                [
                    {"key": "email", "type": "person", "value": "a@b.com", "operator": "exact"},
                    {"key": "my-other-flag", "type": "flag", "value": "true", "operator": "exact"},
                ],
            ),
        ]
    )
    def test_hog_flow_user_blast_radius_rejects_flag_condition(self, _name, properties):
        # Feature flags can't be sized as a static batch audience — reject with a clean 400 before
        # the condition reaches the blast-radius query (where it would otherwise 500).
        with patch("products.workflows.backend.api.hog_flow.get_user_blast_radius") as mock_get_user_blast_radius:
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/user_blast_radius",
                {"filters": {"properties": properties}},
            )

        assert response.status_code == 400, response.json()
        assert "Feature flags can't be used as a batch audience condition" in response.json().get("detail", "")
        mock_get_user_blast_radius.assert_not_called()

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_internal_user_blast_radius_rejects_flag_condition(self):
        with patch("products.workflows.backend.api.hog_flow.get_user_blast_radius") as mock_get_user_blast_radius:
            response = self.client.post(
                f"/api/projects/{self.team.id}/internal/hog_flows/user_blast_radius",
                {"filters": {"properties": [{"key": "my-other-flag", "type": "flag", "value": "true"}]}},
                format="json",
                headers={"x-internal-api-secret": "test-secret-123"},
            )

        assert response.status_code == 400, response.json()
        assert "Feature flags can't be used as a batch audience condition" in response.json().get("error", "")
        mock_get_user_blast_radius.assert_not_called()

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_internal_user_blast_radius_persons_rejects_flag_condition(self):
        with patch(
            "products.workflows.backend.api.hog_flow.get_user_blast_radius_persons"
        ) as mock_get_user_blast_radius_persons:
            response = self.client.post(
                f"/api/projects/{self.team.id}/internal/hog_flows/user_blast_radius_persons",
                {"filters": {"properties": [{"key": "my-other-flag", "type": "flag", "value": "true"}]}},
                format="json",
                headers={"x-internal-api-secret": "test-secret-123"},
            )

        assert response.status_code == 400, response.json()
        assert "Feature flags can't be used as a batch audience condition" in response.json().get("error", "")
        mock_get_user_blast_radius_persons.assert_not_called()

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_internal_update_batch_job_status_marks_completed(self, _mock_dispatch):
        hog_flow = HogFlow.objects.create(team=self.team, name="Test", trigger={}, actions=[], edges=[])
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=hog_flow, status="active")

        response = self.client.put(
            f"/api/projects/{self.team.id}/internal/hog_flows/batch_jobs/{batch_job.id}/status",
            {"status": "completed"},
            content_type="application/json",
            headers={"x-internal-api-secret": "test-secret-123"},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "completed"
        assert response.json()["no_op"] is False
        batch_job.refresh_from_db()
        assert batch_job.status == "completed"

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_internal_update_batch_job_status_is_idempotent_when_already_terminal(self, _mock_dispatch):
        hog_flow = HogFlow.objects.create(team=self.team, name="Test", trigger={}, actions=[], edges=[])
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=hog_flow, status="completed")

        response = self.client.put(
            f"/api/projects/{self.team.id}/internal/hog_flows/batch_jobs/{batch_job.id}/status",
            {"status": "failed"},
            content_type="application/json",
            headers={"x-internal-api-secret": "test-secret-123"},
        )

        # Already terminal → no-op, original status preserved
        assert response.status_code == 200, response.json()
        assert response.json()["no_op"] is True
        assert response.json()["status"] == "completed"
        batch_job.refresh_from_db()
        assert batch_job.status == "completed"

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_internal_update_batch_job_status_rejects_invalid_status(self, _mock_dispatch):
        hog_flow = HogFlow.objects.create(team=self.team, name="Test", trigger={}, actions=[], edges=[])
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=hog_flow, status="active")

        response = self.client.put(
            f"/api/projects/{self.team.id}/internal/hog_flows/batch_jobs/{batch_job.id}/status",
            {"status": "active"},  # not a terminal state
            content_type="application/json",
            headers={"x-internal-api-secret": "test-secret-123"},
        )

        assert response.status_code == 400, response.json()
        batch_job.refresh_from_db()
        assert batch_job.status == "active"  # unchanged

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_internal_update_batch_job_status_returns_404_for_missing_job(self):
        response = self.client.put(
            f"/api/projects/{self.team.id}/internal/hog_flows/batch_jobs/00000000-0000-0000-0000-000000000000/status",
            {"status": "completed"},
            content_type="application/json",
            headers={"x-internal-api-secret": "test-secret-123"},
        )

        assert response.status_code == 404, response.json()

    @override_settings(INTERNAL_API_SECRET="test-secret-123")
    def test_internal_update_batch_job_status_returns_404_for_invalid_uuid(self):
        # `not-a-uuid` reaches UUIDField → ValidationError, must surface as 404 not 500.
        response = self.client.put(
            f"/api/projects/{self.team.id}/internal/hog_flows/batch_jobs/not-a-uuid/status",
            {"status": "completed"},
            content_type="application/json",
            headers={"x-internal-api-secret": "test-secret-123"},
        )

        assert response.status_code == 404, response.json()

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_internal_update_batch_job_status_requires_internal_api_secret(self, _mock_dispatch):
        hog_flow = HogFlow.objects.create(team=self.team, name="Test", trigger={}, actions=[], edges=[])
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=hog_flow, status="active")

        # No INTERNAL_API_SECRET header → unauthenticated
        response = self.client.put(
            f"/api/projects/{self.team.id}/internal/hog_flows/batch_jobs/{batch_job.id}/status",
            {"status": "completed"},
            content_type="application/json",
        )

        # Endpoint requires internal auth — anything other than 200 is acceptable
        assert response.status_code in (401, 403), response.json()

    def test_billable_action_types_computed_correctly(self):
        """Test that billable_action_types is computed correctly and cannot be overridden by clients"""
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        actions = [
            trigger_action,
            {
                "id": "a1",
                "name": "webhook1",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
            },
            {
                "id": "delay1",
                "name": "delay_action",
                "type": "delay",
                "config": {"duration": 60},
            },  # Non-billable action type
            {
                "id": "a2",
                "name": "webhook2",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example2.com"}}},
            },  # Duplicate function type
        ]

        # Try to set billable_action_types manually (should be ignored)
        hog_flow = {
            "name": "Test Billable Types",
            "actions": actions,
            "billable_action_types": ["fake_type", "another_fake"],  # Client tries to override
        }
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        assert response.status_code == 201, response.json()
        # Should have only unique billable types (deduped), client override ignored
        # The delay action should NOT be included in billable_action_types
        assert response.json()["billable_action_types"] == ["function"]

        # Verify it's stored correctly in database
        flow = HogFlow.objects.get(pk=response.json()["id"])
        assert flow.billable_action_types == ["function"]

        # Verify that we have both function actions and the delay action in the flow
        assert len(flow.actions) == 4  # trigger + 2 functions + 1 delay
        action_types = [action["type"] for action in flow.actions]
        assert "delay" in action_types  # Delay is present
        assert action_types.count("function") == 2  # Two function actions

    def test_billable_action_types_recomputed_on_update(self):
        """Test that billable_action_types is recomputed when HogFlow is updated"""
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        # Create flow with just one function action
        initial_actions = [
            trigger_action,
            {
                "id": "a1",
                "name": "webhook",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
            },
        ]

        hog_flow = {"name": "Test Update Billable Types", "actions": initial_actions}
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        flow_id = response.json()["id"]
        assert response.json()["billable_action_types"] == ["function"]

        # Update to remove function action (no billable actions left)
        updated_actions = [trigger_action]
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"actions": updated_actions}
        )
        assert update_response.status_code == 200, update_response.json()
        assert update_response.json()["billable_action_types"] == []

        # Update again to add multiple webhook actions (same billable type) and a delay (non-billable)
        complex_actions = [
            trigger_action,
            {
                "id": "a1",
                "name": "webhook",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
            },
            {
                "id": "delay1",
                "name": "delay_action",
                "type": "delay",
                "config": {"duration": 30},
            },  # Non-billable action
            {
                "id": "a2",
                "name": "webhook2",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example2.com"}}},
            },
        ]

        # Try to override billable_action_types in update - should be ignored and recomputed
        override_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {
                "actions": complex_actions,
                "billable_action_types": ["fake_type"],  # Try to override
            },
        )
        assert override_response.status_code == 200, override_response.json()
        # Should be recomputed based on actual actions, not the override attempt
        # Delay action should NOT be in billable_action_types
        assert override_response.json()["billable_action_types"] == ["function"]

        # Verify database is consistent
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.billable_action_types == ["function"]

        # Verify that the delay action is present but not counted as billable
        assert len(flow.actions) == 4  # trigger + 2 functions + 1 delay
        action_types = [action["type"] for action in flow.actions]
        assert "delay" in action_types  # Delay is present
        assert action_types.count("function") == 2  # Two function actions

    @override_settings(HOGFLOW_BATCH_TRIGGER_LIMIT=5000, HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS=set())
    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_post_hog_flow_batch_jobs_endpoint_creates_job(self, mock_create_invocation):
        flow_id = self._create_active_hog_flow()

        batch_job_data = {
            "variables": [{"key": "first_name", "value": "Test"}],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/batch_jobs", batch_job_data)

        assert response.status_code == 200, response.json()
        assert response.json()["hog_flow"] == flow_id
        assert response.json()["variables"] == batch_job_data["variables"]
        assert response.json()["status"] == "queued"
        mock_create_invocation.assert_called_once()
        # The per-team audience cap must ride on the invocation so the consumer enforces the team's limit.
        assert mock_create_invocation.call_args.kwargs["max_audience_size"] == 5000

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_post_hog_flow_batch_jobs_passes_elevated_audience_size(self, mock_create_invocation):
        flow_id = self._create_active_hog_flow()

        with override_settings(
            HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED=50000,
            HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS={self.team.id},
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}/batch_jobs",
                {"variables": [{"key": "first_name", "value": "Test"}]},
            )

        assert response.status_code == 200, response.json()
        mock_create_invocation.assert_called_once()
        assert mock_create_invocation.call_args.kwargs["max_audience_size"] == 50000

    def test_post_hog_flow_batch_jobs_endpoint_rejects_non_active_workflow(self):
        # A batch run is gated on an enabled workflow — a draft (or archived) one can't start a broadcast.
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}}
        )
        create_response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/batch_jobs",
            {"variables": [{"key": "first_name", "value": "Test"}]},
        )
        assert response.status_code == 400, response.json()
        assert "active" in response.json()["detail"].lower()

    def test_post_hog_flow_batch_jobs_endpoint_nonexistent_flow(self):
        batch_job_data = {"variables": [{"key": "first_name", "value": "Test"}]}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/99999/batch_jobs", batch_job_data)

        assert response.status_code == 404, response.json()

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_get_hog_flow_batch_jobs_only_returns_jobs_for_flow(self, mock_create_invocation):
        # Both must be active — the batch_jobs POST is gated on an enabled workflow.
        flow_id = self._create_active_hog_flow()
        flow_id_2 = self._create_active_hog_flow()

        # Create batch jobs for both flows
        batch_job_data_1 = {"variables": [{"key": "first_name", "value": "Test1"}]}
        batch_job_data_2 = {"variables": [{"key": "first_name", "value": "Test2"}]}

        job_response_1 = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/batch_jobs", batch_job_data_1
        )
        assert job_response_1.status_code == 200, job_response_1.json()

        job_response_2 = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id_2}/batch_jobs", batch_job_data_2
        )
        assert job_response_2.status_code == 200, job_response_2.json()

        # Fetch jobs for the first flow
        get_response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/batch_jobs")
        assert get_response.status_code == 200, get_response.json()
        jobs = get_response.json()
        assert len(jobs) == 1
        assert jobs[0]["id"] == job_response_1.json()["id"]

    def test_hog_flow_filter_test_accounts_compiles_bytecode(self):
        """Test that filter_test_accounts includes team's test account filters in bytecode"""
        # Set up test account filters on the team
        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ]
        self.team.save()

        # Create a workflow WITHOUT filter_test_accounts
        trigger_action_without_filter = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }

        hog_flow_without = {
            "name": "Test Flow Without Filter",
            "status": "active",
            "actions": [trigger_action_without_filter],
        }

        response_without = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow_without)
        assert response_without.status_code == 201, response_without.json()

        # Bytecode should just check for $pageview event
        bytecode_without = response_without.json()["trigger"]["filters"]["bytecode"]
        assert bytecode_without == ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]

        # Create a workflow WITH filter_test_accounts: true
        trigger_action_with_filter = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
                "filter_test_accounts": True,
            },
        }

        hog_flow_with = {
            "name": "Test Flow With Filter",
            "status": "active",
            "actions": [trigger_action_with_filter],
        }

        response_with = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow_with)
        assert response_with.status_code == 201, response_with.json()

        # Bytecode should be in trigger.filters.bytecode
        trigger_filters = response_with.json()["trigger"]["filters"]
        bytecode_with = trigger_filters["bytecode"]

        # The bytecode should be longer and include the test account filter check
        assert len(bytecode_with) > len(bytecode_without), "Bytecode with filter_test_accounts should be longer"

        # Verify the bytecode includes the test account filter pattern
        # The pattern "%@posthog.com%" indicates the not_icontains check
        assert "%@posthog.com%" in bytecode_with, "Bytecode should include test account filter value"
        assert "email" in bytecode_with, "Bytecode should include email property check"
        assert "person" in bytecode_with, "Bytecode should include person property type"

    def test_hog_flow_draft_compiles_bytecode_for_complete_actions(self):
        hog_flow, action = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        hog_flow["status"] = "draft"

        action["filters"] = {
            "properties": [{"key": "event", "type": "event_metadata", "value": ["custom_event"], "operator": "exact"}]
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)

        assert response.status_code == 201, response.json()
        flow = HogFlow.objects.get(pk=response.json()["id"])

        assert flow.trigger["filters"].get("bytecode") == ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]

        assert flow.actions[1]["filters"].get("bytecode") == ["_H", 1, 32, "custom_event", 32, "event", 1, 1, 11]

        assert flow.actions[1]["config"]["inputs"] == {
            "url": {"order": 0, "value": "https://example.com", "bytecode": ["_H", 1, 32, "https://example.com"]}
        }

    def test_hog_flow_draft_to_active_compiles_bytecode(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        hog_flow["status"] = "draft"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        flow_id = response.json()["id"]

        # Activate the draft — re-validation should compile bytecodes
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": "active"},
        )
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.trigger["filters"].get("bytecode") == ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]
        assert flow.actions[1]["config"]["inputs"] == {
            "url": {"order": 0, "value": "https://example.com", "bytecode": ["_H", 1, 32, "https://example.com"]}
        }

    def test_hog_flow_draft_partial_inputs_skips_input_bytecode(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {},
            }
        )
        hog_flow["status"] = "draft"

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()

        flow = HogFlow.objects.get(pk=response.json()["id"])

        # Trigger filter bytecode should still compile even though action inputs are incomplete
        assert flow.trigger["filters"].get("bytecode") == ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11]

        # Action inputs should NOT have bytecode since required 'url' is missing
        # (is_valid() fails on the whole inputs serializer)
        assert flow.actions[1]["config"]["inputs"] == {}

    def _get_hog_flow_activity(self, flow_id: Optional[str] = None) -> list:
        params: dict = {"scope": "HogFlow", "page": 1, "limit": 20}
        if flow_id:
            params["item_id"] = flow_id
        activity = self.client.get(f"/api/projects/{self.team.pk}/activity_log", data=params)
        assert activity.status_code == status.HTTP_200_OK
        return activity.json().get("results")

    def test_create_hog_flow_logs_activity(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        flow_id = response.json()["id"]
        flow_name = response.json()["name"]

        activity = self._get_hog_flow_activity(flow_id)
        assert len(activity) >= 1

        latest = activity[0]
        assert latest["activity"] == "created"
        assert latest["scope"] == "HogFlow"
        assert latest["item_id"] == flow_id
        assert latest["detail"]["name"] == flow_name
        assert latest["detail"]["type"] == "standard"

    def test_update_hog_flow_logs_activity(self):
        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        flow_id = response.json()["id"]
        original_name = response.json()["name"]

        new_name = "Updated Flow Name"
        update_response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"name": new_name})
        assert update_response.status_code == status.HTTP_200_OK, update_response.json()

        activity = self._get_hog_flow_activity(flow_id)
        assert len(activity) >= 2

        latest = activity[0]
        assert latest["activity"] == "updated"
        assert latest["scope"] == "HogFlow"
        assert latest["item_id"] == flow_id
        assert latest["detail"]["name"] == new_name
        changes = latest["detail"]["changes"]
        name_change = next((c for c in changes if c["field"] == "name"), None)
        assert name_change is not None
        assert name_change["before"] == original_name
        assert name_change["after"] == new_name

    def test_hog_flow_draft_allows_incomplete_actions(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        incomplete_action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {},
        }

        hog_flow = {
            "name": "Draft Flow",
            "status": "draft",
            "actions": [trigger_action, incomplete_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        assert response.json()["status"] == "draft"

    def test_hog_flow_active_rejects_incomplete_actions(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        incomplete_action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {},
        }

        hog_flow = {
            "name": "Active Flow",
            "status": "active",
            "actions": [trigger_action, incomplete_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 400, response.json()

    def test_hog_flow_retrieve_does_not_leak_between_teams(self):
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)
        another_user = User.objects.create_and_join(another_org, "other-hog-flow@example.com", password="")

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )

        self.client.force_login(another_user)
        create_response = self.client.post(f"/api/projects/{another_team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        self.client.force_login(self.user)
        response = self.client.get(f"/api/projects/{another_team.id}/hog_flows/{flow_id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_hog_flow_create_does_not_leak_between_teams(self):
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )

        self.client.force_login(self.user)
        response = self.client.post(f"/api/projects/{another_team.id}/hog_flows", hog_flow)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_hog_flow_update_does_not_leak_between_teams(self):
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)
        another_user = User.objects.create_and_join(another_org, "other-hog-flow-update@example.com", password="")

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )

        self.client.force_login(another_user)
        create_response = self.client.post(f"/api/projects/{another_team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        self.client.force_login(self.user)
        response = self.client.patch(
            f"/api/projects/{another_team.id}/hog_flows/{flow_id}",
            {"name": "updated by unauthorized user"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_hog_flow_delete_does_not_leak_between_teams(self):
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)
        another_user = User.objects.create_and_join(another_org, "other-hog-flow-delete@example.com", password="")

        hog_flow, _ = self._create_hog_flow_with_action(
            {
                "template_id": "template-webhook",
                "inputs": {"url": {"value": "https://example.com"}},
            }
        )

        self.client.force_login(another_user)
        create_response = self.client.post(f"/api/projects/{another_team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201, create_response.json()
        flow_id = create_response.json()["id"]

        self.client.force_login(self.user)
        response = self.client.delete(f"/api/projects/{another_team.id}/hog_flows/{flow_id}")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_hog_flow_draft_invalid_can_be_archived(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        incomplete_action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {},
        }

        hog_flow = {
            "name": "Draft to Archive Flow",
            "status": "draft",
            "actions": [trigger_action, incomplete_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        flow_id = response.json()["id"]
        assert response.json()["status"] == "draft"

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": "archived"},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["status"] == "archived"

    def test_hog_flow_draft_to_active_rejects_incomplete(self):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        incomplete_action = {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {},
        }

        hog_flow = {
            "name": "Draft to Active Flow",
            "status": "draft",
            "actions": [trigger_action, incomplete_action],
        }

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        flow_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": "active"},
        )
        assert response.status_code == 400, response.json()

    def _create_flow(self, name: str = "Test Flow", flow_status: str = "draft") -> str:
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
        )
        hog_flow["name"] = name
        hog_flow["status"] = flow_status
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == 201, response.json()
        return response.json()["id"]

    def _archive_flow(self, flow_id: str) -> None:
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": "archived"},
        )
        assert response.status_code == 200, response.json()

    def test_bulk_delete_archived_workflows(self):
        ids = [self._create_flow(name=f"Flow {i}") for i in range(3)]
        for fid in ids:
            self._archive_flow(fid)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": ids},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["deleted"] == 3
        assert HogFlow.objects.filter(id__in=ids).count() == 0

    @parameterized.expand(
        [
            ("draft",),
            ("active",),
        ]
    )
    def test_bulk_delete_skips_non_archived_workflows(self, flow_status):
        flow_id = self._create_flow(flow_status=flow_status)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": [flow_id]},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["deleted"] == 0
        assert HogFlow.objects.filter(id=flow_id).exists()

    def test_bulk_delete_mixed_statuses_only_deletes_archived(self):
        draft_id = self._create_flow(name="Draft", flow_status="draft")
        archived_id = self._create_flow(name="Archived", flow_status="draft")
        self._archive_flow(archived_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": [draft_id, archived_id]},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["deleted"] == 1
        assert HogFlow.objects.filter(id=draft_id).exists()
        assert not HogFlow.objects.filter(id=archived_id).exists()

    def test_bulk_delete_rejects_empty_ids(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": []},
        )
        assert response.status_code == 400

    def test_bulk_delete_rejects_missing_ids(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {},
        )
        assert response.status_code == 400

    def test_bulk_delete_rejects_invalid_uuids(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": ["not-a-uuid", "also-bad"]},
        )
        assert response.status_code == 400

    def test_bulk_delete_does_not_leak_between_teams(self):
        another_org = Organization.objects.create(name="other org")
        another_team = Team.objects.create(organization=another_org)
        another_user = User.objects.create_and_join(another_org, "other-bulk-delete@example.com", password="")

        self.client.force_login(another_user)
        hog_flow, _ = self._create_hog_flow_with_action(
            {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
        )
        create_response = self.client.post(f"/api/projects/{another_team.id}/hog_flows", hog_flow)
        assert create_response.status_code == 201
        flow_id = create_response.json()["id"]
        self.client.patch(f"/api/projects/{another_team.id}/hog_flows/{flow_id}", {"status": "archived"})

        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/bulk_delete",
            {"ids": [flow_id]},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["deleted"] == 0
        assert HogFlow.objects.filter(id=flow_id).exists()

    def _base_hog_flow_with_variables(self, variables):
        trigger_action = {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        }
        return {
            "name": "Test Flow",
            "actions": [trigger_action],
            "variables": variables,
        }

    @parameterized.expand(
        [
            (
                "unique_keys_accepted",
                [{"key": "name", "value": ""}, {"key": "email", "value": ""}],
                201,
                None,
            ),
            (
                "duplicate_keys_rejected",
                [{"key": "name", "value": ""}, {"key": "name", "value": "other"}],
                400,
                "Variable keys must be unique",
            ),
            (
                "exceeding_5kb_rejected",
                [{"key": f"var_{i}", "value": "x" * 1000} for i in range(6)],
                400,
                "Total size of variables definition must be less than 5KB",
            ),
            (
                "just_under_5kb_accepted",
                [{"key": f"v_{i:02d}", "value": "x" * 1200} for i in range(4)],
                201,
                None,
            ),
        ]
    )
    def test_variables_validation(self, _name, variables, expected_status, expected_error):
        hog_flow = self._base_hog_flow_with_variables(variables)
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert response.status_code == expected_status, response.json()
        if expected_error:
            assert response.json()["detail"] == expected_error


class TestHogFlowGlobalStats(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.flow_a = HogFlow.objects.create(team=self.team, name="Flow A")
        self.flow_b = HogFlow.objects.create(team=self.team, name="Flow B")

    def _global(self, params=None):
        return self.client.get(f"/api/projects/{self.team.id}/hog_flows/metrics/global/", params)

    def _seed(self, workflow_id, *, succeeded=0, failed=0, timestamp=None, team_id=None, app_source="hog_flow"):
        tid = team_id or self.team.pk
        if succeeded:
            create_app_metric2(
                team_id=tid,
                app_source=app_source,
                app_source_id=str(workflow_id),
                metric_kind="success",
                metric_name="succeeded",
                count=succeeded,
                timestamp=timestamp,
            )
        if failed:
            create_app_metric2(
                team_id=tid,
                app_source=app_source,
                app_source_id=str(workflow_id),
                metric_kind="failure",
                metric_name="failed",
                count=failed,
                timestamp=timestamp,
            )

    def test_returns_empty_when_no_metrics(self):
        res = self._global()
        assert res.status_code == status.HTTP_200_OK
        assert res.json() == []

    def test_aggregates_per_workflow_sorted_most_failing_first(self):
        self._seed(self.flow_a.id, succeeded=3, failed=1)
        self._seed(self.flow_b.id, succeeded=5, failed=4)
        rows = self._global().json()
        by_id = {r["workflow_id"]: r for r in rows}
        assert by_id[str(self.flow_a.id)] == {"workflow_id": str(self.flow_a.id), "succeeded": 3, "failed": 1}
        assert by_id[str(self.flow_b.id)] == {"workflow_id": str(self.flow_b.id), "succeeded": 5, "failed": 4}
        # Most-failing first.
        assert rows[0]["workflow_id"] == str(self.flow_b.id)

    def test_time_window_filter(self):
        now = datetime.now(tz=UTC)
        self._seed(self.flow_a.id, failed=4, timestamp=now)
        self._seed(self.flow_a.id, failed=9, timestamp=now - timedelta(days=30))
        recent = {r["workflow_id"]: r for r in self._global({"after": "-7d"}).json()}
        assert recent[str(self.flow_a.id)]["failed"] == 4
        wide = {r["workflow_id"]: r for r in self._global({"after": "-60d"}).json()}
        assert wide[str(self.flow_a.id)]["failed"] == 13

    def test_after_filter_respects_team_timezone(self):
        # PT is UTC-7 in June, so after='2026-06-08T00:00:00' resolves to 07:00 UTC. The 06:00 UTC
        # row must fall outside the window and the 08:00 UTC row inside — a naive bound read as
        # 00:00 UTC would count both.
        self.team.timezone = "America/Los_Angeles"
        self.team.save()
        self._seed(self.flow_a.id, failed=1, timestamp=datetime(2026, 6, 8, 6, 0, 0, tzinfo=UTC))
        self._seed(self.flow_a.id, failed=1, timestamp=datetime(2026, 6, 8, 8, 0, 0, tzinfo=UTC))
        rows = self._global({"after": "2026-06-08T00:00:00", "before": "2026-06-09T00:00:00"}).json()
        assert {r["workflow_id"]: r["failed"] for r in rows} == {str(self.flow_a.id): 1}

    def test_isolated_from_other_team_and_app_source(self):
        self._seed(self.flow_a.id, succeeded=2)
        # Same id but a hog_function metric, and another team — neither must leak in.
        self._seed(self.flow_a.id, succeeded=7, app_source="hog_function")
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self._seed(self.flow_a.id, succeeded=99, team_id=other_team.pk)
        rows = self._global().json()
        assert {r["workflow_id"]: r["succeeded"] for r in rows} == {str(self.flow_a.id): 2}

    def test_excludes_metrics_for_workflows_not_in_queryset(self):
        # Metrics are intersected with workflows the caller can see, so a row for an id that isn't a
        # live workflow (e.g. since-deleted, or one the caller can't access) must not leak in.
        self._seed(self.flow_a.id, failed=2)
        self._seed("00000000-0000-0000-0000-000000000000", failed=9)
        rows = self._global().json()
        assert {r["workflow_id"] for r in rows} == {str(self.flow_a.id)}

    def test_personal_api_key_hog_flow_read_only_allowed(self):
        # Aggregate counts carry no person data, so hog_flow:read alone is sufficient (no person:read).
        self._seed(self.flow_a.id, failed=1)
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="hog_flow only", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:read"]
        )
        res = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/metrics/global/",
            headers={"authorization": f"Bearer {key}"},
        )
        assert res.status_code == status.HTTP_200_OK, res.json()
        assert {r["workflow_id"] for r in res.json()} == {str(self.flow_a.id)}
