from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models.activity_logging.activity_log import ActivityLog

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.api.hog_flow import DRAFT_CONTENT_FIELDS
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision

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


class TestHogFlowRevisions(APIBaseTest):
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

    def _create_active_three_step_flow(self) -> str:
        hog_flow = {
            "name": "Revision Flow",
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

    def _live_edit(self, flow_id: str, url: str = "https://changed.example.com"):
        return self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": [_trigger_action(), _webhook_action(url=url)]},
        )

    def _stage_draft(self, flow_id: str, url: str = "https://changed.example.com"):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": [_trigger_action(), _webhook_action(url=url)]},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 200, response.json()

    def _publish(self, flow_id: str):
        with patch("products.workflows.backend.api.hog_flow.get_hog_flow_in_flight_count") as mock_count:
            mock_count.return_value = MagicMock(
                status_code=200, json=lambda: {"count": 0, "by_action": {}, "position_unknown": 0}
            )
            preview = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish", {})
        assert preview.status_code == 200, preview.json()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
            {"confirm": True, "confirm_token": preview.json()["confirm_token"]},
        )
        assert response.status_code == 200, response.json()
        return response

    def _list_revisions(self, flow_id: str) -> list[dict]:
        # Assert through the endpoint, not the ORM, so these exercise its team scoping, ordering
        # (newest-first), and serialization (content omitted). Requires the flag on for a 200.
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions")
        assert response.status_code == 200, response.json()
        return response.json()["results"]

    def _revision_content(self, flow_id: str, version: int) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions/{version}")
        assert response.status_code == 200, response.json()
        return response.json()["content"]

    # ── Appending on live-content writes ─────────────────────────────

    @patch(FLAG_PATH, return_value=True)
    def test_publish_appends_revision_and_bumps_version(self, _flag):
        flow_id = self._create_active_flow()
        self._stage_draft(flow_id)
        published = self._publish(flow_id)
        assert published.json()["workflow"]["version"] == 2

        revisions = self._list_revisions(flow_id)
        # Newest-first: v2 (this user's publish) then the v1 bootstrap snapshot (no author)
        assert [r["version"] for r in revisions] == [2, 1]
        assert revisions[0]["created_by"]["id"] == self.user.id
        assert revisions[1]["created_by"] is None
        # First write also snapshots the outgoing live content, so there's always a state to roll back to
        v1_urls = [
            a["config"]["inputs"]["url"]["value"]
            for a in self._revision_content(flow_id, 1)["actions"]
            if a["type"] == "function"
        ]
        assert v1_urls == ["https://example.com"]
        v2_content = self._revision_content(flow_id, 2)
        v2_urls = [a["config"]["inputs"]["url"]["value"] for a in v2_content["actions"] if a["type"] == "function"]
        assert v2_urls == ["https://changed.example.com"]
        # Content is exactly the draft-cycle content fields — no system bookkeeping
        assert set(v2_content.keys()) == set(DRAFT_CONTENT_FIELDS)

    @patch(FLAG_PATH, return_value=True)
    def test_web_live_edit_appends_revision(self, _flag):
        flow_id = self._create_active_flow()
        response = self._live_edit(flow_id)
        assert response.status_code == 200, response.json()
        assert response.json()["version"] == 2
        assert [r["version"] for r in self._list_revisions(flow_id)] == [2, 1]

    @patch(FLAG_PATH, return_value=True)
    def test_graph_live_edit_appends_revision(self, _flag):
        flow_id = self._create_active_three_step_flow()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "remove_action", "id": "action_1"}]},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["version"] == 2
        assert [r["version"] for r in self._list_revisions(flow_id)] == [2, 1]
        assert "action_1" not in [a["id"] for a in self._revision_content(flow_id, 2)["actions"]]

    @parameterized.expand(
        [
            ("draft_staging", {"actions": [_trigger_action(), _webhook_action(url="https://d.example.com")]}, "mcp"),
            ("metadata_only", {"name": "Renamed"}, None),
            ("status_only", {"status": "draft"}, None),
        ]
    )
    def test_non_content_writes_do_not_append_revisions(self, _name, payload, client_header):
        flow_id = self._create_active_flow()
        with patch(FLAG_PATH, return_value=True):
            extra = {"HTTP_X_POSTHOG_CLIENT": client_header} if client_header else {}
            response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", payload, **extra)
            assert response.status_code == 200, response.json()
            assert self._list_revisions(flow_id) == []
        assert response.json()["version"] == 1

    @patch(FLAG_PATH, return_value=True)
    def test_no_op_live_edit_does_not_append_revision(self, _flag):
        # Two identical saves in a row: the first may change stored shape (create vs update
        # serializer defaults differ), but the second must not append a junk revision.
        flow_id = self._create_active_flow()
        first = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": [_trigger_action(), _webhook_action()]},
        )
        assert first.status_code == 200, first.json()
        revisions_after_first = [r["version"] for r in self._list_revisions(flow_id)]

        second = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": [_trigger_action(), _webhook_action()]},
        )
        assert second.status_code == 200, second.json()
        assert [r["version"] for r in self._list_revisions(flow_id)] == revisions_after_first

    @patch(FLAG_PATH, return_value=False)
    def test_flag_off_appends_no_revisions(self, _flag):
        flow_id = self._create_active_flow()
        response = self._live_edit(flow_id)
        assert response.status_code == 200, response.json()
        assert response.json()["version"] == 1
        # Flag off: the list endpoint is rejected (see test_flag_off_rejects_revision_endpoints), so
        # assert directly that nothing was persisted.
        assert not HogFlowRevision.objects.for_team(self.team.id).filter(hog_flow_id=flow_id).exists()

    # ── Listing and fetching ─────────────────────────────────────────

    @patch(FLAG_PATH, return_value=True)
    def test_list_and_retrieve_revisions(self, _flag):
        flow_id = self._create_active_flow()
        self._live_edit(flow_id)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions")
        assert response.status_code == 200, response.json()
        results = response.json()["results"]
        assert [r["version"] for r in results] == [2, 1]
        assert results[0]["created_by"]["id"] == self.user.id
        assert results[1]["created_by"] is None, "the bootstrap snapshot has no author and must serialize as null"
        assert "content" not in results[0]

        detail = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions/1")
        assert detail.status_code == 200, detail.json()
        urls = [
            a["config"]["inputs"]["url"]["value"]
            for a in detail.json()["content"]["actions"]
            if a["type"] == "function"
        ]
        assert urls == ["https://example.com"]

    @patch(FLAG_PATH, return_value=True)
    def test_retrieve_missing_revision_404s(self, _flag):
        flow_id = self._create_active_flow()
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions/99")
        assert response.status_code == 404, response.json()

    # ── Restore (rollback) ───────────────────────────────────────────

    @patch(FLAG_PATH, return_value=True)
    def test_restore_copies_revision_into_draft_without_touching_live(self, _flag):
        flow_id = self._create_active_flow()
        self._live_edit(flow_id)
        live_actions = HogFlow.objects.get(pk=flow_id).actions

        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions/1/restore", {})
        assert response.status_code == 200, response.json()

        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.actions == live_actions
        assert flow.draft is not None
        assert flow.draft_updated_at is not None
        draft_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.draft["actions"] if a["type"] == "function"]
        assert draft_urls == ["https://example.com"]

        # Restore must stay distinguishable from a plain edit in the audit trail
        entry = ActivityLog.objects.filter(scope="HogFlow", item_id=flow_id).order_by("-created_at").first()
        assert entry is not None and entry.activity == "revision_restored"

    @patch(FLAG_PATH, return_value=True)
    def test_rollback_round_trip_restores_live_and_prunes_redirects(self, _flag):
        # Publish v2 deleting a step (parked runs get a redirect), then roll back to v1: the step
        # comes back, its redirect entry is pruned, and the rollback is recorded as a new revision.
        flow_id = self._create_active_three_step_flow()
        self._stage_draft_delete_action_1(flow_id)
        self._publish(flow_id)
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.action_redirects == {"action_1": "action_2"}

        restore = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions/1/restore", {})
        assert restore.status_code == 200, restore.json()
        self._publish(flow_id)

        flow = HogFlow.objects.get(pk=flow_id)
        assert "action_1" in [a["id"] for a in flow.actions]
        assert flow.action_redirects is None, "re-adding the deleted step must prune its redirect entry"
        assert flow.draft is None
        assert [r["version"] for r in self._list_revisions(flow_id)] == [3, 2, 1]

    def _stage_draft_delete_action_1(self, flow_id: str) -> None:
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {
                "actions": [_trigger_action(), _webhook_action("action_2")],
                "edges": [{"from": "trigger_node", "to": "action_2", "type": "continue"}],
            },
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 200, response.json()

    @patch(FLAG_PATH, return_value=True)
    def test_restore_with_open_draft_conflicts_unless_overwrite(self, _flag):
        flow_id = self._create_active_flow()
        self._live_edit(flow_id)
        self._stage_draft(flow_id, url="https://staged.example.com")

        conflict = self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions/1/restore", {})
        assert conflict.status_code == 409, conflict.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is not None
        staged_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.draft["actions"] if a["type"] == "function"]
        assert staged_urls == ["https://staged.example.com"], "a rejected restore must not clobber the open draft"

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/revisions/1/restore", {"overwrite": True}
        )
        assert response.status_code == 200, response.json()
        flow = HogFlow.objects.get(pk=flow_id)
        assert flow.draft is not None
        draft_urls = [a["config"]["inputs"]["url"]["value"] for a in flow.draft["actions"] if a["type"] == "function"]
        assert draft_urls == ["https://example.com"]

    @parameterized.expand([("list", "GET", "revisions"), ("restore", "POST", "revisions/1/restore")])
    def test_flag_off_rejects_revision_endpoints(self, _name, method, path):
        flow_id = self._create_active_flow()
        with patch(FLAG_PATH, return_value=False):
            response = getattr(self.client, method.lower())(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}/{path}", {} if method == "POST" else None
            )
        assert response.status_code == 400, response.json()
