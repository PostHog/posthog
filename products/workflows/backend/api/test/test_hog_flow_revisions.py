from posthog.test.base import APIBaseTest

from posthog.cdp.templates.hog_function_template import sync_template_to_db

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow.hog_flow_revision import CONTENT_FIELDS, HogFlowRevision

webhook_template = MOCK_NODE_TEMPLATES[0]


class TestHogFlowDoubleWrite(APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(webhook_template)

    def _draft_flow_payload(self) -> dict:
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
        return {
            "name": "Test Flow",
            "status": "draft",
            "actions": [trigger, action, exit_action],
            "edges": [
                {"from": "trigger_node", "to": "action_1", "type": "continue"},
                {"from": "action_1", "to": "exit_1", "type": "continue"},
            ],
        }

    def _create_draft(self) -> str:
        create = self.client.post(f"/api/projects/{self.team.id}/hog_flows", self._draft_flow_payload())
        assert create.status_code == 201, create.json()
        return create.json()["id"]

    def _assert_mirror_in_sync(self, flow_id: str) -> None:
        flow = HogFlow.objects.get(id=flow_id)
        revisions = list(flow.revisions.all())
        # The mirror is exactly one revision per flow - never accumulates rows or collides on (team, version).
        assert len(revisions) == 1, f"expected a single mirror revision, got {len(revisions)}"
        revision = revisions[0]
        assert revision.team_id == flow.team_id
        assert revision.status == flow.status
        for field in CONTENT_FIELDS:
            assert getattr(revision, field) == getattr(flow, field), f"revision.{field} drifted from HogFlow"
        # active_revision points at the mirror only while the workflow is live.
        if flow.status == HogFlow.State.ACTIVE:
            assert flow.active_revision_id == revision.id
        else:
            assert flow.active_revision_id is None

    def test_create_draft_mirrors_into_draft_revision_without_active_pointer(self):
        flow_id = self._create_draft()
        self._assert_mirror_in_sync(flow_id)
        assert HogFlow.objects.get(id=flow_id).active_revision_id is None

    def test_lifecycle_keeps_single_mirror_revision_in_sync(self):
        # Guards the double-write across the full status lifecycle: a missed sync drifts the revision
        # from HogFlow content, and a bad transition would create a second v1 row and hit the unique
        # (team, hog_flow, version) constraint.
        flow_id = self._create_draft()
        self._assert_mirror_in_sync(flow_id)

        # Edit while draft.
        self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"name": "Renamed draft"})
        self._assert_mirror_in_sync(flow_id)

        # Enable (draft -> active): the mirror flips to active and active_revision starts pointing at it.
        self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
        self._assert_mirror_in_sync(flow_id)
        assert HogFlow.objects.get(id=flow_id).active_revision_id is not None

        # Edit while active (web path, no MCP header so it's allowed).
        self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"name": "Renamed active"})
        self._assert_mirror_in_sync(flow_id)

        # Disable (active -> draft): active_revision is cleared again.
        self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "draft"})
        self._assert_mirror_in_sync(flow_id)
        assert HogFlow.objects.get(id=flow_id).active_revision_id is None

        # Re-enable: pointer comes back, still exactly one revision row.
        self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
        self._assert_mirror_in_sync(flow_id)
        assert HogFlowRevision.objects.filter(hog_flow_id=flow_id).count() == 1

    def test_graph_edit_syncs_mirror_revision(self):
        # The graph endpoint is a separate write path; assert it also keeps the mirror in sync.
        flow_id = self._create_draft()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
            {"operations": [{"op": "update_action", "id": "action_1", "patch": {"name": "renamed via graph"}}]},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )
        assert response.status_code == 200, response.json()
        self._assert_mirror_in_sync(flow_id)
        revision = HogFlowRevision.objects.get(hog_flow_id=flow_id)
        assert any(a.get("name") == "renamed via graph" for a in revision.actions)
