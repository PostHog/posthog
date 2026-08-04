from copy import deepcopy

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.messaging.backend.unlayer import UnlayerRenderError
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision

webhook_template = MOCK_NODE_TEMPLATES[0]

RENDER_PATH = "products.workflows.backend.api.hog_flow.render_design_html"
RENDERED_HTML = "<html>rendered</html>"


def _email_function_template() -> dict:
    template = deepcopy(webhook_template)
    template["id"] = "template-email"
    template["name"] = "Email"
    template["inputs_schema"] = [
        {
            "key": "email",
            "type": "native_email",
            "label": "Email",
            "secret": False,
            "hidden": False,
            "required": True,
            "templating": "liquid",
        }
    ]
    return template


def _design() -> dict:
    return {
        "counters": {"u_row": 1, "u_column": 1, "u_content_text": 1},
        "schemaVersion": 16,
        "body": {
            "id": "body_1",
            "rows": [
                {
                    "id": "row_1",
                    "cells": [1],
                    "columns": [
                        {
                            "id": "col_1",
                            "contents": [{"id": "text_1", "type": "text", "values": {"text": "<p>Hello</p>"}}],
                            "values": {},
                        }
                    ],
                    "values": {},
                }
            ],
            "values": {},
        },
    }


def _email_value(with_design: bool = True) -> dict:
    value = {
        "to": {"email": "{{ person.properties.email }}", "name": ""},
        "from": "noreply@example.com",
        "subject": "Old subject",
        "preheader": "Old preheader",
        "text": "Hello",
        "html": "<p>Hello</p>",
    }
    if with_design:
        value["design"] = _design()
    return value


def _trigger_action() -> dict:
    return {
        "id": "trigger_node",
        "name": "trigger_1",
        "type": "trigger",
        "config": {
            "type": "event",
            "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
        },
    }


def _email_action(with_design: bool = True) -> dict:
    return {
        "id": "email_1",
        "name": "Email step",
        "type": "function_email",
        "config": {
            "template_id": "template-email",
            "inputs": {"email": {"value": _email_value(with_design), "templating": "liquid"}},
        },
    }


def _webhook_action() -> dict:
    return {
        "id": "action_1",
        "name": "action_1",
        "type": "function",
        "config": {"template_id": "template-webhook", "inputs": {"url": {"value": "https://example.com"}}},
    }


def _stored_email_value(flow: HogFlow, from_draft: bool = False) -> dict:
    actions = ((flow.draft or {}).get("actions") if from_draft else flow.actions) or []
    action = next(a for a in actions if a["id"] == "email_1")
    return action["config"]["inputs"]["email"]["value"]


class TestHogFlowActionEmailAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(webhook_template)
        sync_template_to_db(_email_function_template())

    def _create_flow(self, status: str = "draft", with_design: bool = True) -> str:
        flow = {
            "name": "Email Flow",
            "status": "draft",
            "actions": [_trigger_action(), _email_action(with_design), _webhook_action()],
            "edges": [
                {"from": "trigger_node", "to": "email_1", "type": "continue"},
                {"from": "email_1", "to": "action_1", "type": "continue"},
            ],
        }
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", flow)
        assert create.status_code == 201, create.json()
        flow_id = create.json()["id"]
        if status != "draft":
            activate = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": status})
            assert activate.status_code == 200, activate.json()
        return flow_id

    def _patch_email(self, flow_id: str, body: dict, action_id: str = "email_1", mcp: bool = True):
        url = f"/api/projects/{self.team.id}/hog_flows/{flow_id}/actions/{action_id}/email"
        if mcp:
            return self.client.patch(url, body, HTTP_X_POSTHOG_CLIENT="mcp")
        return self.client.patch(url, body)

    @patch(RENDER_PATH, return_value=RENDERED_HTML)
    def test_design_op_updates_block_and_rerenders_html(self, mock_render):
        flow_id = self._create_flow()
        response = self._patch_email(
            flow_id,
            {
                "operations": [
                    {"op": "update_content", "id": "text_1", "patch": {"values": {"text": "<p>New copy</p>"}}}
                ]
            },
        )
        assert response.status_code == 200, response.json()

        email = _stored_email_value(HogFlow.objects.get(pk=flow_id))
        contents = email["design"]["body"]["rows"][0]["columns"][0]["contents"]
        assert contents[0]["values"]["text"] == "<p>New copy</p>"
        # html is re-rendered from the patched design so the sent email can't go stale.
        assert email["html"] == RENDERED_HTML
        assert email["subject"] == "Old subject"
        mock_render.assert_called_once()

    @patch(RENDER_PATH, return_value=RENDERED_HTML)
    def test_email_patch_merges_fields_without_rerendering(self, mock_render):
        flow_id = self._create_flow()
        response = self._patch_email(
            flow_id, {"email_patch": {"subject": "New subject", "preheader": None, "text": "New text"}}
        )
        assert response.status_code == 200, response.json()

        email = _stored_email_value(HogFlow.objects.get(pk=flow_id))
        assert email["subject"] == "New subject"
        assert email["text"] == "New text"
        # A null leaf deletes the key, mirroring the design ops' merge semantics.
        assert "preheader" not in email
        # No design change, so the stored html must be preserved, not re-rendered.
        assert email["html"] == "<p>Hello</p>"
        mock_render.assert_not_called()

    @parameterized.expand(
        [
            ("design", {"design": {"body": {}}}),
            ("html", {"html": "<p>injected</p>"}),
        ]
    )
    def test_email_patch_rejects_derived_keys(self, _name, patch_body):
        flow_id = self._create_flow()
        response = self._patch_email(flow_id, {"email_patch": patch_body})
        assert response.status_code == 400, response.json()
        assert "email_patch" in str(response.json())

    def test_requires_operations_or_email_patch(self):
        flow_id = self._create_flow()
        response = self._patch_email(flow_id, {})
        assert response.status_code == 400, response.json()

    def test_unknown_action_id_rejected(self):
        flow_id = self._create_flow()
        response = self._patch_email(flow_id, {"email_patch": {"subject": "x"}}, action_id="ghost")
        assert response.status_code == 400, response.json()
        assert "ghost" in str(response.json())

    def test_non_email_action_rejected(self):
        flow_id = self._create_flow()
        response = self._patch_email(flow_id, {"email_patch": {"subject": "x"}}, action_id="action_1")
        assert response.status_code == 400, response.json()
        assert "email" in str(response.json())

    @patch(RENDER_PATH, return_value=RENDERED_HTML)
    def test_operations_without_design_rejected(self, _mock_render):
        flow_id = self._create_flow(with_design=False)
        response = self._patch_email(
            flow_id,
            {"operations": [{"op": "update_content", "id": "text_1", "patch": {"values": {"text": "x"}}}]},
        )
        assert response.status_code == 400, response.json()
        assert "design" in str(response.json())

    @patch(RENDER_PATH, return_value=RENDERED_HTML)
    def test_unknown_content_id_rejected_without_partial_write(self, _mock_render):
        flow_id = self._create_flow()
        response = self._patch_email(
            flow_id,
            {
                "operations": [{"op": "update_content", "id": "nope", "patch": {"values": {"text": "x"}}}],
                "email_patch": {"subject": "New subject"},
            },
        )
        assert response.status_code == 400, response.json()
        # Atomicity: the rejected batch leaves the stored email untouched, including the merge half.
        email = _stored_email_value(HogFlow.objects.get(pk=flow_id))
        assert email["subject"] == "Old subject"

    @patch(RENDER_PATH, side_effect=UnlayerRenderError("render exploded"))
    def test_render_failure_rejected_without_partial_write(self, _mock_render):
        flow_id = self._create_flow()
        response = self._patch_email(
            flow_id,
            {"operations": [{"op": "update_content", "id": "text_1", "patch": {"values": {"text": "x"}}}]},
        )
        assert response.status_code == 400, response.json()
        email = _stored_email_value(HogFlow.objects.get(pk=flow_id))
        assert email["html"] == "<p>Hello</p>"
        assert email["design"]["body"]["rows"][0]["columns"][0]["contents"][0]["values"]["text"] == "<p>Hello</p>"

    def test_design_moved_between_render_and_lock_rejected_with_409(self):
        flow_id = self._create_flow()

        def concurrent_edit_lands_during_render(design: dict) -> str:
            # Stand in for another writer committing between the pre-lock render and the locked
            # apply: the render call is the last thing that runs before the transaction opens.
            flow = HogFlow.objects.get(pk=flow_id)
            email = next(a for a in flow.actions if a["id"] == "email_1")
            text_block = email["config"]["inputs"]["email"]["value"]["design"]["body"]["rows"][0]["columns"][0][
                "contents"
            ][0]
            text_block["values"]["text"] = "<p>Concurrent copy</p>"
            HogFlow.objects.filter(pk=flow_id).update(actions=flow.actions)
            return RENDERED_HTML

        with patch(RENDER_PATH, side_effect=concurrent_edit_lands_during_render):
            response = self._patch_email(
                flow_id,
                {"operations": [{"op": "update_content", "id": "text_1", "patch": {"values": {"text": "<p>New</p>"}}}]},
            )

        assert response.status_code == 409, response.json()
        email = _stored_email_value(HogFlow.objects.get(pk=flow_id))
        # The concurrent edit survives, and the stale pre-rendered html never lands.
        assert (
            email["design"]["body"]["rows"][0]["columns"][0]["contents"][0]["values"]["text"]
            == "<p>Concurrent copy</p>"
        )
        assert email["html"] == "<p>Hello</p>"

    # ── Draft routing (mirrors the /graph endpoint's contract) ────────

    @patch(RENDER_PATH, return_value=RENDERED_HTML)
    def test_mcp_patch_on_active_flow_lands_in_draft(self, _mock_render):
        flow_id = self._create_flow(status="active")
        live_actions_before = HogFlow.objects.get(pk=flow_id).actions

        response = self._patch_email(flow_id, {"email_patch": {"subject": "Draft subject"}})
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.actions == live_actions_before
        assert flow.draft is not None
        assert _stored_email_value(flow, from_draft=True)["subject"] == "Draft subject"
        assert response.json()["draft"] is not None

    @patch(RENDER_PATH, return_value=RENDERED_HTML)
    def test_mcp_patch_composes_on_existing_draft(self, _mock_render):
        # A graph patch stages a draft first; the email patch must apply on that draft, not reset it.
        flow_id = self._create_flow(status="active")
        graph = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "update_action", "id": "email_1", "patch": {"name": "Renamed step"}}]},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert graph.status_code == 200, graph.json()

        response = self._patch_email(flow_id, {"email_patch": {"subject": "Draft subject"}})
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is not None
        draft_action = next(a for a in flow.draft["actions"] if a["id"] == "email_1")
        assert draft_action["name"] == "Renamed step"
        assert draft_action["config"]["inputs"]["email"]["value"]["subject"] == "Draft subject"

    @patch(RENDER_PATH, return_value=RENDERED_HTML)
    def test_design_ops_compose_on_a_drafted_design(self, _mock_render):
        # Two consecutive draft design edits: the second must render against the draft's design,
        # not the live one, or the apply reads it as a concurrent edit and conflicts.
        flow_id = self._create_flow(status="active")
        ops = [{"op": "update_content", "id": "text_1", "patch": {"values": {"text": "<p>First</p>"}}}]
        first = self._patch_email(flow_id, {"operations": ops})
        assert first.status_code == 200, first.json()

        ops[0]["patch"] = {"values": {"text": "<p>Second</p>"}}
        second = self._patch_email(flow_id, {"operations": ops})
        assert second.status_code == 200, second.json()

        email = _stored_email_value(HogFlow.objects.get(pk=flow_id), from_draft=True)
        assert email["design"]["body"]["rows"][0]["columns"][0]["contents"][0]["values"]["text"] == "<p>Second</p>"

    @patch(RENDER_PATH, return_value=RENDERED_HTML)
    def test_stale_base_updated_at_rejected_with_409(self, _mock_render):
        flow_id = self._create_flow(status="active")
        first = self._patch_email(flow_id, {"email_patch": {"subject": "First"}})
        assert first.status_code == 200, first.json()

        response = self._patch_email(
            flow_id,
            {"email_patch": {"subject": "Second"}, "base_updated_at": "2020-01-01T00:00:00Z"},
        )
        assert response.status_code == 409, response.json()

    @patch(RENDER_PATH, return_value=RENDERED_HTML)
    def test_web_patch_on_active_flow_applies_live_and_bumps_revision(self, _mock_render):
        flow_id = self._create_flow(status="active")

        response = self._patch_email(flow_id, {"email_patch": {"subject": "Live subject"}}, mcp=False)
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is None
        assert _stored_email_value(flow)["subject"] == "Live subject"
        # A live content change must land in the revision history so it can be rolled back to.
        latest = HogFlowRevision.objects.for_team(self.team.id).filter(hog_flow_id=flow_id).order_by("-version").first()
        assert latest is not None
        latest_email = next(a for a in latest.content["actions"] if a["id"] == "email_1")
        assert latest_email["config"]["inputs"]["email"]["value"]["subject"] == "Live subject"
