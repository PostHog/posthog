from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models.activity_logging.activity_log import ActivityLog

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision

webhook_template = MOCK_NODE_TEMPLATES[0]


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
        # Graph content edits over MCP go through the surgical graph endpoint (a plain update
        # rejects actions/edges outright), so drafts are staged the way real agents stage them.
        return self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {
                "operations": [
                    {
                        "op": "update_action",
                        "id": "action_1",
                        "patch": {"config": {"inputs": {"url": {"value": url}}}},
                    }
                ]
            },
            HTTP_X_POSTHOG_CLIENT="mcp",
        )

    # ── Draft routing ────────────────────────────────────────────────

    def test_mcp_content_edit_on_active_flow_routes_to_draft(self):
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

    def test_web_content_edit_on_active_flow_still_applies_live(self):
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

    def test_web_content_edit_with_stage_draft_routes_to_draft_and_applies_metadata_live(self):
        flow_id = self._create_active_flow()
        live_actions_before = HogFlow.objects.get(pk=flow_id).actions

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {
                "actions": [_trigger_action(), _webhook_action(url="https://changed.example.com")],
                "name": "Renamed live",
                "stage_draft": True,
            },
        )
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.actions == live_actions_before
        assert flow.draft is not None
        assert flow.draft_updated_at is not None
        draft_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.draft["actions"] if a["type"] == "function"]
        assert draft_urls == ["https://changed.example.com"]
        assert flow.name == "Renamed live"
        assert response.json()["draft"] is not None

    def test_web_stage_draft_saves_incomplete_content_leniently(self):
        # The builder auto-saves mid-edit, so a staged draft must accept a step whose required
        # inputs aren't filled in yet; strict validation would 400 every auto-save while the
        # user iterates. Publish still revalidates strictly (see the companion test below).
        flow_id = self._create_active_flow()
        live_actions_before = HogFlow.objects.get(pk=flow_id).actions

        incomplete = _webhook_action()
        incomplete["config"]["inputs"] = {}
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": [_trigger_action(), incomplete], "stage_draft": True},
        )
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.actions == live_actions_before
        assert flow.draft is not None

    def test_web_deploy_on_save_of_incomplete_content_stays_strict(self):
        # Without stage_draft a web PATCH on an active workflow deploys immediately, so the
        # lenient staged-draft path must not leak into it.
        flow_id = self._create_active_flow()

        incomplete = _webhook_action()
        incomplete["config"]["inputs"] = {}
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": [_trigger_action(), incomplete]},
        )
        assert response.status_code == 400, response.json()

    def test_publish_of_incomplete_draft_is_rejected(self):
        flow_id = self._create_active_flow()
        incomplete = _webhook_action()
        incomplete["config"]["inputs"] = {}
        staged = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": [_trigger_action(), incomplete], "stage_draft": True},
        )
        assert staged.status_code == 200, staged.json()

        preview = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", {"confirm": False})
        assert preview.status_code == 200, preview.json()
        confirm = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "confirm_token": preview.json()["confirm_token"]},
        )
        assert confirm.status_code == 400, confirm.json()
        # The failed publish must leave both the live config and the draft untouched.
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is not None
        assert all(a["config"].get("inputs") for a in flow.actions if a["type"] == "function")

    def test_discard_bumps_live_stamp_so_stale_draft_saves_get_409(self):
        # Without the bump, a concurrent editor holding the discarded draft's stamp would pass the
        # staleness guard (which falls back to the live stamp once the draft is gone) and silently
        # resurrect the draft it never learned was discarded.
        flow_id = self._create_active_flow()
        staged = self._patch_actions_via_mcp(flow_id)
        assert staged.status_code == 200, staged.json()
        draft_stamp = HogFlow.objects.get(pk=flow_id).draft_updated_at
        assert draft_stamp is not None

        live_before_discard = HogFlow.objects.get(pk=flow_id).updated_at
        discard = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/discard_draft")
        assert discard.status_code == 200, discard.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.updated_at > live_before_discard

        resave = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {
                "actions": [_trigger_action(), _webhook_action(url="https://resurrect.example.com")],
                "stage_draft": True,
                "base_updated_at": draft_stamp.isoformat(),
            },
        )
        assert resave.status_code == 409, resave.json()
        assert HogFlow.objects.get(pk=flow_id).draft is None

    def test_restore_with_stale_expected_draft_stamp_is_rejected_with_409(self):
        flow_id = self._create_active_flow()
        # Revisions only snapshot live-content changes, so make one to have a version to restore.
        live_edit = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": [_trigger_action(), _webhook_action(url="https://live-v2.example.com")]},
        )
        assert live_edit.status_code == 200, live_edit.json()
        revision = (
            HogFlowRevision.objects.for_team(self.team.id).filter(hog_flow_id=flow_id).order_by("version").first()
        )
        assert revision is not None
        version = revision.version

        first = self._patch_actions_via_mcp(flow_id, url="https://first-draft.example.com")
        assert first.status_code == 200, first.json()
        stamp_at_dialog = HogFlow.objects.get(pk=flow_id).draft_updated_at
        assert stamp_at_dialog is not None

        second = self._patch_actions_via_mcp(flow_id, url="https://second-draft.example.com")
        assert second.status_code == 200, second.json()

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions/{version}/restore",
            {"overwrite": True, "expected_draft_updated_at": stamp_at_dialog.isoformat()},
        )
        assert response.status_code == 409, response.json()
        draft = HogFlow.objects.get(pk=flow_id).draft
        assert draft is not None
        draft_urls = [a["config"]["inputs"]["url"]["value"] for a in draft["actions"] if a["type"] == "function"]
        assert draft_urls == ["https://second-draft.example.com"]

    def test_stage_draft_on_inactive_flow_applies_live(self):
        hog_flow = {"name": "Test Flow", "actions": [_trigger_action(), _webhook_action()]}
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", hog_flow)
        flow_id = create.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {
                "actions": [_trigger_action(), _webhook_action(url="https://changed.example.com")],
                "stage_draft": True,
            },
        )
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is None
        live_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.actions if a["type"] == "function"]
        assert live_urls == ["https://changed.example.com"]

    def test_mcp_content_edit_on_inactive_flow_applies_live(self):
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

    def test_mcp_metadata_edit_on_active_flow_applies_live_without_draft(self):
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

    def test_mcp_mixed_status_and_content_still_rejected(self):
        flow_id = self._create_active_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"status": "draft", "name": "Renamed"},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 400, response.json()

    def test_stale_draft_edit_is_rejected_with_409(self):
        flow_id = self._create_active_flow()
        first = self._patch_actions_via_mcp(flow_id)
        assert first.status_code == 200, first.json()

        stale = "2020-01-01T00:00:00Z"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {
                "operations": [
                    {
                        "op": "update_action",
                        "id": "action_1",
                        "patch": {"config": {"inputs": {"url": {"value": "https://other.example.com"}}}},
                    }
                ],
                "base_updated_at": stale,
            },
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 409, response.json()

    # ── Graph patch routing ──────────────────────────────────────────

    def test_mcp_graph_patch_on_active_flow_lands_in_draft(self):
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

    def test_mcp_graph_patch_composes_on_existing_draft(self):
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

    # ── Publish ──────────────────────────────────────────────────────

    def _stage_draft(self, flow_id: str) -> HogFlow:
        response = self._patch_actions_via_mcp(flow_id)
        assert response.status_code == 200, response.json()
        return HogFlow.objects.get(pk=flow_id)

    def _publish_preview(self, flow_id: str, counts: dict | None = None):
        with patch("products.workflows.backend.api.hog_flow.get_hog_flow_in_flight_count") as mock_count:
            if counts is None:
                mock_count.side_effect = Exception("count service down")
            else:
                mock_count.return_value = MagicMock(status_code=200, json=lambda: counts)
            response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", {})
        assert response.status_code == 200, response.json()
        return response

    @patch("products.workflows.backend.api.hog_flow.get_hog_flow_in_flight_count")
    def test_publish_without_confirm_returns_impact_only(self, mock_count):
        mock_count.return_value = MagicMock(
            status_code=200, json=lambda: {"count": 42, "by_action": {"action_1": 42}, "position_unknown": 0}
        )
        flow_id = self._create_active_flow()
        flow = self._stage_draft(flow_id)
        live_actions_before = flow.actions

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", {})
        assert response.status_code == 200, response.json()
        assert response.json()["in_flight_runs"] == 42
        assert response.json()["draft_updated_at"] is not None
        assert response.json()["confirm_token"]
        # Content-only edit: impact present but empty — nothing to warn about
        assert response.json()["impact"] == {
            "deleted_steps": [],
            "position_unknown": 0,
            "empty_variables": [],
            "schedule_conflicts": [],
        }

        flow.refresh_from_db()
        assert flow.actions == live_actions_before
        assert flow.draft is not None

    @patch("products.workflows.backend.api.hog_flow.get_hog_flow_in_flight_count")
    def test_publish_impact_degrades_to_null_counts_when_unavailable(self, mock_count):
        mock_count.side_effect = Exception("node service down")
        flow_id = self._create_active_flow()
        self._stage_draft(flow_id)

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", {})
        assert response.status_code == 200, response.json()
        assert response.json()["in_flight_runs"] is None
        # Graph-derived impact still renders; only the counts degrade
        assert response.json()["impact"]["position_unknown"] is None

    @patch("products.workflows.backend.api.hog_flow.get_hog_flow_in_flight_count")
    def test_publish_preview_reports_deleted_step_moves(self, mock_count):
        mock_count.return_value = MagicMock(
            status_code=200, json=lambda: {"count": 7, "by_action": {"action_1": 5}, "position_unknown": 2}
        )
        flow_id = self._create_active_three_step_flow()
        stage = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "remove_action", "id": "action_1"}]},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert stage.status_code == 200, stage.json()

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", {})
        assert response.status_code == 200, response.json()
        impact = response.json()["impact"]
        assert impact["deleted_steps"] == [
            {
                "action_id": "action_1",
                "name": "action_1",
                "runs": 5,
                "moves_to": {"action_id": "action_2", "name": "action_2"},
                "exits": False,
            }
        ]
        assert impact["position_unknown"] == 2

    def test_publish_with_confirm_promotes_draft_and_clears_it(self):
        flow_id = self._create_active_flow()
        flow = self._stage_draft(flow_id)
        confirm_token = self._publish_preview(flow_id).json()["confirm_token"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "confirm_token": confirm_token},
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

        # Publish must stay distinguishable from a plain edit in the audit trail
        entry = ActivityLog.objects.filter(scope="HogFlow", item_id=flow_id).order_by("-created_at").first()
        assert entry is not None and entry.activity == "published"

    def test_publish_with_stale_token_after_draft_reedit_is_rejected_with_409(self):
        flow_id = self._create_active_flow()
        self._stage_draft(flow_id)
        confirm_token = self._publish_preview(flow_id).json()["confirm_token"]
        # The draft changes between preview and confirm — the token no longer matches what's staged
        reedit = self._patch_actions_via_mcp(flow_id, url="https://reedited.example.com")
        assert reedit.status_code == 200, reedit.json()

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "confirm_token": confirm_token},
        )
        assert response.status_code == 409, response.json()

    @parameterized.expand(
        [
            ("no_draft", False, "garbage"),
            ("no_token", True, None),
            ("forged_token", True, "not-a-signed-value:1a2b3c:forged"),
        ]
    )
    def test_publish_rejected(self, _name, stage_draft, confirm_token):
        flow_id = self._create_active_flow()
        if stage_draft:
            self._stage_draft(flow_id)
        payload: dict = {"confirm": True}
        if confirm_token is not None:
            payload["confirm_token"] = confirm_token
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", payload)
        assert response.status_code == 400, response.json()

    def test_publish_with_expired_token_is_rejected(self):
        flow_id = self._create_active_flow()
        with freeze_time("2026-01-01T00:00:00Z"):
            self._stage_draft(flow_id)
            confirm_token = self._publish_preview(flow_id).json()["confirm_token"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "confirm_token": confirm_token},
        )
        assert response.status_code == 400, response.json()

    def test_publish_validates_draft_strictly(self):
        # A draft written by some future lenient path must not promote unvalidated: publish is defensive
        # regardless of who wrote the blob
        flow_id = self._create_active_flow()
        flow = self._stage_draft(flow_id)
        assert flow.draft is not None
        confirm_token = self._publish_preview(flow_id).json()["confirm_token"]
        # Tampering via the ORM leaves draft_updated_at untouched, so the token stays valid —
        # strict revalidation is what must catch the bad blob
        flow.draft = {**flow.draft, "actions": [{"id": "bad", "type": "function", "config": {}}]}
        flow.save(update_fields=["draft"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "confirm_token": confirm_token},
        )
        assert response.status_code == 400, response.json()

        flow.refresh_from_db()
        live_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.actions if a["type"] == "function"]
        assert live_urls == ["https://example.com"], "a failed publish must leave the live config untouched"

    # ── Discard ──────────────────────────────────────────────────────

    def test_discard_draft_clears_it(self):
        flow_id = self._create_active_flow()
        self._stage_draft(flow_id)

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/discard_draft", {})
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is None
        assert flow.draft_updated_at is None

        entry = ActivityLog.objects.filter(scope="HogFlow", item_id=flow_id).order_by("-created_at").first()
        assert entry is not None and entry.activity == "draft_discarded"

    # ── Test-run from draft ──────────────────────────────────────────

    @patch("products.workflows.backend.api.hog_flow.create_hog_flow_invocation_test")
    def test_invocation_with_use_draft_sends_draft_as_configuration(self, mock_invoke):
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

    def test_invocation_with_use_draft_and_no_draft_is_rejected(self):
        flow_id = self._create_active_flow()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/invocations",
            {"use_draft": True, "globals": {"event": {"event": "$pageview", "properties": {}}}},
        )
        assert response.status_code == 400, response.json()

    # ── Serializer exposure ──────────────────────────────────────────

    def test_get_surfaces_open_draft(self):
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

    def test_publish_deleting_a_step_persists_its_redirect(self):
        flow_id = self._create_active_three_step_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "remove_action", "id": "action_1"}]},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.action_redirects is None, "staging a draft must not touch the live redirect map"
        confirm_token = self._publish_preview(flow_id).json()["confirm_token"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "confirm_token": confirm_token},
        )
        assert response.status_code == 200, response.json()
        # Re-fetch rather than refresh_from_db: the is-None assert above narrows the attribute
        # type, and mypy doesn't un-narrow on refresh, flagging the asserts below as unreachable
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.action_redirects == {"action_1": "action_2"}
        assert response.json()["workflow"]["action_redirects"] == {"action_1": "action_2"}

    def test_web_edit_deleting_a_step_persists_its_redirect(self):
        flow_id = self._create_active_three_step_flow()
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", self._DELETE_ACTION_1_PAYLOAD)
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.action_redirects == {"action_1": "action_2"}

    def test_edit_while_disabled_still_persists_its_redirect(self):
        # Disabling a flow doesn't purge its parked runs — a step deleted during a disable/re-enable
        # window must still get a redirect, or those runs strand on re-activation.
        flow_id = self._create_active_three_step_flow()
        disable = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "draft"})
        assert disable.status_code == 200, disable.json()

        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", self._DELETE_ACTION_1_PAYLOAD)
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.action_redirects == {"action_1": "action_2"}

    def test_graph_remove_action_persists_its_redirect(self):
        flow_id = self._create_active_three_step_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "remove_action", "id": "action_1"}]},
        )
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.action_redirects == {"action_1": "action_2"}

    def test_draft_contents_are_masked_in_activity_log(self):
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
