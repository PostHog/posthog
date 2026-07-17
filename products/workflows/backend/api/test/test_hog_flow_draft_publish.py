from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models.activity_logging.activity_log import ActivityLog

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

webhook_template = MOCK_NODE_TEMPLATES[0]

FLAG_PATH = "products.workflows.backend.api.hog_flow.use_workflows_revisions"


def _trigger_action() -> dict:
    return {
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


def _webhook_action(action_id: str = "action_1", url: str = "https://example.com") -> dict:
    return {
        "id": action_id,
        "name": action_id,
        "type": "function",
        "config": {"template_id": "template-webhook", "inputs": {"url": {"value": url}}},
    }


class TestHogFlowDraftPublish(APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(webhook_template)

    def _create_active_flow(self) -> str:
        hog_flow = {"name": "Test Flow", "actions": [_trigger_action(), _webhook_action()]}
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create.status_code == 201, create.json()
        flow_id = create.json()["id"]
        activate = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
        assert activate.status_code == 200, activate.json()
        return flow_id

    def _patch_actions_via_mcp(self, flow_id: str, url: str = "https://changed.example.com"):
        return self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": [_trigger_action(), _webhook_action(url=url)]},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )

    # ── Draft routing ────────────────────────────────────────────────

    @patch(FLAG_PATH, return_value=True)
    def test_mcp_content_edit_on_active_flow_routes_to_draft(self, _flag):
        flow_id = self._create_active_flow()
        live_actions_before = HogFlow.objects.get(pk=flow_id).actions

        response = self._patch_actions_via_mcp(flow_id)
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.actions == live_actions_before
        assert flow.draft is not None
        assert flow.draft_updated_at is not None
        draft_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.draft["actions"] if a["type"] == "function"]
        assert draft_urls == ["https://changed.example.com"]
        # The response surfaces the draft so callers can see what they staged
        assert response.json()["draft"] is not None

    @patch(FLAG_PATH, return_value=False)
    def test_mcp_content_edit_on_active_flow_rejected_when_flag_off(self, _flag):
        flow_id = self._create_active_flow()
        response = self._patch_actions_via_mcp(flow_id)
        assert response.status_code == 400, response.json()
        assert "active workflow isn't supported via MCP" in response.json()["detail"]

    @patch(FLAG_PATH, return_value=True)
    def test_web_content_edit_on_active_flow_still_applies_live(self, _flag):
        flow_id = self._create_active_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": [_trigger_action(), _webhook_action(url="https://changed.example.com")]},
        )
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is None
        live_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.actions if a["type"] == "function"]
        assert live_urls == ["https://changed.example.com"]

    @patch(FLAG_PATH, return_value=True)
    def test_mcp_content_edit_on_inactive_flow_applies_live(self, _flag):
        # Disabled/draft-status workflows edit in place — the draft cycle protects in-flight runs only
        hog_flow = {"name": "Test Flow", "actions": [_trigger_action(), _webhook_action()]}
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        flow_id = create.json()["id"]

        response = self._patch_actions_via_mcp(flow_id)
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is None
        live_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.actions if a["type"] == "function"]
        assert live_urls == ["https://changed.example.com"]

    @patch(FLAG_PATH, return_value=True)
    def test_mcp_metadata_edit_on_active_flow_applies_live_without_draft(self, _flag):
        flow_id = self._create_active_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"name": "Renamed live"},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.name == "Renamed live"
        assert flow.draft is None

    @patch(FLAG_PATH, return_value=True)
    def test_mcp_mixed_status_and_content_still_rejected(self, _flag):
        flow_id = self._create_active_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": "draft", "name": "Renamed"},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 400, response.json()

    @patch(FLAG_PATH, return_value=True)
    def test_stale_draft_edit_is_rejected_with_409(self, _flag):
        flow_id = self._create_active_flow()
        first = self._patch_actions_via_mcp(flow_id)
        assert first.status_code == 200, first.json()

        stale = "2020-01-01T00:00:00Z"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {
                "actions": [_trigger_action(), _webhook_action(url="https://other.example.com")],
                "base_updated_at": stale,
            },
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 409, response.json()

    # ── Graph patch routing ──────────────────────────────────────────

    @patch(FLAG_PATH, return_value=True)
    def test_mcp_graph_patch_on_active_flow_lands_in_draft(self, _flag):
        flow_id = self._create_active_flow()
        live_actions_before = HogFlow.objects.get(pk=flow_id).actions

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {
                "operations": [
                    {
                        "op": "update_action",
                        "id": "action_1",
                        "patch": {"config": {"inputs": {"url": {"value": "https://patched.example.com"}}}},
                    }
                ]
            },
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.actions == live_actions_before
        assert flow.draft is not None
        draft_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.draft["actions"] if a["type"] == "function"]
        assert draft_urls == ["https://patched.example.com"]

    @patch(FLAG_PATH, return_value=True)
    def test_mcp_graph_patch_composes_on_existing_draft(self, _flag):
        # A second surgical patch must apply against the staged draft, not reset it from live
        flow_id = self._create_active_flow()
        first = self._patch_actions_via_mcp(flow_id, url="https://draft-v1.example.com")
        assert first.status_code == 200, first.json()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {
                "operations": [
                    {
                        "op": "add_action",
                        "action": _webhook_action(action_id="action_2", url="https://added.example.com"),
                        "edges": [{"from": "action_1", "to": "action_2", "type": "continue"}],
                    }
                ]
            },
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is not None
        draft_urls = {a["config"]["inputs"]["url"]["value"] for a in flow.draft["actions"] if a["type"] == "function"}
        assert draft_urls == {"https://draft-v1.example.com", "https://added.example.com"}

    @patch(FLAG_PATH, return_value=False)
    def test_mcp_graph_patch_on_active_flow_rejected_when_flag_off(self, _flag):
        flow_id = self._create_active_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {
                "operations": [
                    {
                        "op": "update_action",
                        "id": "action_1",
                        "patch": {"config": {"inputs": {"url": {"value": "https://patched.example.com"}}}},
                    }
                ]
            },
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 400, response.json()

    # ── Publish ──────────────────────────────────────────────────────

    def _stage_draft(self, flow_id: str) -> HogFlow:
        with patch(FLAG_PATH, return_value=True):
            response = self._patch_actions_via_mcp(flow_id)
            assert response.status_code == 200, response.json()
        return HogFlow.objects.get(pk=flow_id)

    @patch("products.workflows.backend.api.hog_flow.get_hog_flow_in_flight_count")
    @patch(FLAG_PATH, return_value=True)
    def test_publish_without_confirm_returns_impact_only(self, _flag, mock_count):
        mock_count.return_value = MagicMock(status_code=200, json=lambda: {"count": 42})
        flow_id = self._create_active_flow()
        flow = self._stage_draft(flow_id)
        live_actions_before = flow.actions

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", {})
        assert response.status_code == 200, response.json()
        assert response.json()["in_flight_runs"] == 42
        assert response.json()["draft_updated_at"] is not None

        flow.refresh_from_db()
        assert flow.actions == live_actions_before
        assert flow.draft is not None

    @patch("products.workflows.backend.api.hog_flow.get_hog_flow_in_flight_count")
    @patch(FLAG_PATH, return_value=True)
    def test_publish_impact_degrades_to_null_when_count_unavailable(self, _flag, mock_count):
        mock_count.side_effect = Exception("node service down")
        flow_id = self._create_active_flow()
        self._stage_draft(flow_id)

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", {})
        assert response.status_code == 200, response.json()
        assert response.json()["in_flight_runs"] is None

    @patch(FLAG_PATH, return_value=True)
    def test_publish_with_confirm_promotes_draft_and_clears_it(self, _flag):
        flow_id = self._create_active_flow()
        flow = self._stage_draft(flow_id)
        # Narrow a local, not the attribute — narrowing flow.draft_updated_at here would make the
        # post-publish `is None` assertion unreachable in mypy's eyes (it can't see refresh_from_db)
        staged_at = flow.draft_updated_at
        assert staged_at is not None

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "draft_updated_at": staged_at.isoformat()},
        )
        assert response.status_code == 200, response.json()

        flow.refresh_from_db()
        live_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.actions if a["type"] == "function"]
        assert live_urls == ["https://changed.example.com"]
        assert flow.draft is None
        assert flow.draft_updated_at is None
        # Bytecode is recompiled through the normal serializer path on publish
        trigger = next(a for a in flow.actions if a["type"] == "trigger")
        assert trigger["config"]["filters"].get("bytecode"), "publish must compile trigger filter bytecode"

    @patch(FLAG_PATH, return_value=True)
    def test_publish_with_stale_draft_pointer_is_rejected_with_409(self, _flag):
        flow_id = self._create_active_flow()
        self._stage_draft(flow_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "draft_updated_at": "2020-01-01T00:00:00Z"},
        )
        assert response.status_code == 409, response.json()

    @parameterized.expand(
        [
            ("flag_off", False, True),
            ("no_draft", True, False),
        ]
    )
    def test_publish_rejected(self, _name, flag_on, stage_draft):
        flow_id = self._create_active_flow()
        if stage_draft:
            self._stage_draft(flow_id)
        with patch(FLAG_PATH, return_value=flag_on):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
                {"confirm": True, "draft_updated_at": "2026-01-01T00:00:00Z"},
            )
        assert response.status_code == 400, response.json()

    @patch(FLAG_PATH, return_value=True)
    def test_publish_validates_draft_strictly(self, _flag):
        # A draft written by some future lenient path must not promote unvalidated: publish is defensive
        # regardless of who wrote the blob
        flow_id = self._create_active_flow()
        flow = self._stage_draft(flow_id)
        assert flow.draft is not None
        assert flow.draft_updated_at is not None
        flow.draft = {**flow.draft, "actions": [{"id": "bad", "type": "function", "config": {}}]}
        flow.save(update_fields=["draft"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "draft_updated_at": flow.draft_updated_at.isoformat()},
        )
        assert response.status_code == 400, response.json()

        flow.refresh_from_db()
        live_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.actions if a["type"] == "function"]
        assert live_urls == ["https://example.com"], "a failed publish must leave the live config untouched"

    # ── Discard ──────────────────────────────────────────────────────

    @patch(FLAG_PATH, return_value=True)
    def test_discard_draft_clears_it(self, _flag):
        flow_id = self._create_active_flow()
        self._stage_draft(flow_id)

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/discard_draft", {})
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is None
        assert flow.draft_updated_at is None

    # ── Test-run from draft ──────────────────────────────────────────

    @patch("products.workflows.backend.api.hog_flow.create_hog_flow_invocation_test")
    @patch(FLAG_PATH, return_value=True)
    def test_invocation_with_use_draft_sends_draft_as_configuration(self, _flag, mock_invoke):
        mock_invoke.return_value = MagicMock(status_code=200, json=lambda: {"status": "success"})
        flow_id = self._create_active_flow()
        self._stage_draft(flow_id)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/invocations",
            {"use_draft": True, "globals": {"event": {"event": "$pageview", "properties": {}}}},
        )
        assert response.status_code == 200, response.json()

        payload = mock_invoke.call_args.kwargs["payload"]
        sent_urls = [
            a["config"]["inputs"]["url"]["value"]
            for a in payload["configuration"]["actions"]
            if a["type"] == "function"
        ]
        assert sent_urls == ["https://changed.example.com"]

    @patch(FLAG_PATH, return_value=True)
    def test_invocation_with_use_draft_and_no_draft_is_rejected(self, _flag):
        flow_id = self._create_active_flow()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/invocations",
            {"use_draft": True, "globals": {"event": {"event": "$pageview", "properties": {}}}},
        )
        assert response.status_code == 400, response.json()

    # ── Serializer exposure ──────────────────────────────────────────

    @patch(FLAG_PATH, return_value=True)
    def test_get_surfaces_open_draft(self, _flag):
        flow_id = self._create_active_flow()
        self._stage_draft(flow_id)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}")
        assert response.status_code == 200, response.json()
        assert response.json()["draft"] is not None
        assert response.json()["draft_updated_at"] is not None

    # ── Skip-forward redirects (deleted steps) ───────────────────────
    # The redirect-walk matrix lives in test_action_redirects.py; these guard the viewset wiring —
    # that each live-graph write path actually computes and persists the map before saving.

    def _create_active_three_step_flow(self) -> str:
        hog_flow = {
            "name": "Redirect Flow",
            "actions": [_trigger_action(), _webhook_action("action_1"), _webhook_action("action_2")],
            "edges": [
                {"from": "trigger_node", "to": "action_1", "type": "continue"},
                {"from": "action_1", "to": "action_2", "type": "continue"},
            ],
        }
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        assert create.status_code == 201, create.json()
        flow_id = create.json()["id"]
        activate = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
        assert activate.status_code == 200, activate.json()
        return flow_id

    _DELETE_ACTION_1_PAYLOAD = {
        "actions": [_trigger_action(), _webhook_action("action_2")],
        "edges": [{"from": "trigger_node", "to": "action_2", "type": "continue"}],
    }

    @patch(FLAG_PATH, return_value=True)
    def test_publish_deleting_a_step_persists_its_redirect(self, _flag):
        flow_id = self._create_active_three_step_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            self._DELETE_ACTION_1_PAYLOAD,
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.action_redirects is None, "staging a draft must not touch the live redirect map"
        assert flow.draft_updated_at is not None

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "draft_updated_at": flow.draft_updated_at.isoformat()},
        )
        assert response.status_code == 200, response.json()
        flow.refresh_from_db()
        assert flow.action_redirects == {"action_1": "action_2"}
        assert response.json()["workflow"]["action_redirects"] == {"action_1": "action_2"}

    @parameterized.expand([("flag_on", True), ("flag_off", False)])
    def test_web_edit_deleting_a_step_persists_its_redirect_only_when_flag_on(self, _name, flag_on):
        flow_id = self._create_active_three_step_flow()
        with patch(FLAG_PATH, return_value=flag_on):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}", self._DELETE_ACTION_1_PAYLOAD
            )
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.action_redirects == ({"action_1": "action_2"} if flag_on else None)

    @patch(FLAG_PATH, return_value=True)
    def test_graph_remove_action_persists_its_redirect(self, _flag):
        flow_id = self._create_active_three_step_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "remove_action", "id": "action_1"}]},
        )
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.action_redirects == {"action_1": "action_2"}

    @patch(FLAG_PATH, return_value=True)
    def test_draft_contents_are_masked_in_activity_log(self, _flag):
        flow_id = self._create_active_flow()
        self._stage_draft(flow_id)

        entry = ActivityLog.objects.filter(scope="HogFlow", item_id=flow_id).order_by("-created_at").first()
        assert entry is not None
        detail = entry.detail
        assert detail is not None
        draft_changes = [c for c in detail["changes"] if c["field"] == "draft"]
        assert draft_changes, detail["changes"]
        for change in draft_changes:
            # Draft snapshots carry action inputs (auth headers, API keys) — contents must never
            # land in team-readable activity rows, only the fact that the draft changed.
            assert change.get("before") in (None, "masked")
            assert change.get("after") in (None, "masked")
