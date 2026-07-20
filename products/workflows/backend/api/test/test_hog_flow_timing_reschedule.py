from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

webhook_template = MOCK_NODE_TEMPLATES[0]

TIMING_FLAG_PATH = "products.workflows.backend.api.hog_flow.use_workflows_timing_reschedule"
REVISIONS_FLAG_PATH = "products.workflows.backend.api.hog_flow.use_workflows_revisions"
TASK_PATH = "products.workflows.backend.api.hog_flow.reschedule_hog_flow_timing"


def _actions(delay_duration: str = "7d", webhook_url: str = "https://example.com") -> list[dict]:
    return [
        {
            "id": "trigger_node",
            "name": "trigger_1",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
            },
        },
        {"id": "delay_1", "name": "delay_1", "type": "delay", "config": {"delay_duration": delay_duration}},
        {
            "id": "action_1",
            "name": "action_1",
            "type": "function",
            "config": {"template_id": "template-webhook", "inputs": {"url": {"value": webhook_url}}},
        },
    ]


def _edges() -> list[dict]:
    return [
        {"from": "trigger_node", "to": "delay_1", "type": "continue"},
        {"from": "delay_1", "to": "action_1", "type": "continue"},
    ]


class TestHogFlowTimingRescheduleTrigger(APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(webhook_template)

    def _create_flow(self, activate: bool = True) -> str:
        create = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {"name": "Test Flow", "actions": _actions(), "edges": _edges()},
        )
        assert create.status_code == 201, create.json()
        flow_id = create.json()["id"]
        if activate:
            response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
            assert response.status_code == 200, response.json()
        return flow_id

    def _patch_actions(self, flow_id: str, delay_duration: str, webhook_url: str = "https://example.com", **extra):
        return self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}",
            {"actions": _actions(delay_duration=delay_duration, webhook_url=webhook_url)},
            **extra,
        )

    @patch(TASK_PATH)
    @patch(TIMING_FLAG_PATH, return_value=True)
    def test_shortened_delay_on_live_save_enqueues_sweep_post_commit(self, _flag, mock_task):
        flow_id = self._create_flow()

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self._patch_actions(flow_id, delay_duration="1d")
        assert response.status_code == 200, response.json()

        assert mock_task.delay.call_count == 0, "the sweep must not start before the new config is committed"
        for callback in callbacks:
            callback()
        mock_task.delay.assert_called_once_with(team_id=self.team.id, hog_flow_id=flow_id, action_ids=["delay_1"])

    @parameterized.expand(
        [
            ("flag_off", False, "1d", "https://example.com"),
            ("lengthened_delay", True, "30d", "https://example.com"),
            ("non_timing_edit", True, "7d", "https://changed.example.com"),
        ]
    )
    @patch(TASK_PATH)
    def test_live_save_does_not_enqueue_sweep(self, _name, flag_on, delay_duration, webhook_url, mock_task):
        flow_id = self._create_flow()

        with patch(TIMING_FLAG_PATH, return_value=flag_on):
            with self.captureOnCommitCallbacks(execute=True):
                response = self._patch_actions(flow_id, delay_duration=delay_duration, webhook_url=webhook_url)

        assert response.status_code == 200, response.json()
        mock_task.delay.assert_not_called()

    @patch(TASK_PATH)
    @patch(TIMING_FLAG_PATH, return_value=True)
    def test_inactive_flow_save_does_not_enqueue_sweep(self, _flag, mock_task):
        flow_id = self._create_flow(activate=False)

        with self.captureOnCommitCallbacks(execute=True):
            response = self._patch_actions(flow_id, delay_duration="1d")

        assert response.status_code == 200, response.json()
        mock_task.delay.assert_not_called()

    @patch(TASK_PATH)
    @patch(TIMING_FLAG_PATH, return_value=True)
    @patch(REVISIONS_FLAG_PATH, return_value=True)
    def test_mcp_draft_routed_edit_does_not_enqueue_sweep(self, _revisions, _timing, mock_task):
        flow_id = self._create_flow()

        with self.captureOnCommitCallbacks(execute=True):
            response = self._patch_actions(flow_id, delay_duration="1d", HTTP_X_POSTHOG_CLIENT="mcp")

        assert response.status_code == 200, response.json()
        assert HogFlow.objects.get(pk=flow_id).draft is not None
        mock_task.delay.assert_not_called()

    @patch(TASK_PATH)
    @patch(TIMING_FLAG_PATH, return_value=True)
    @patch(REVISIONS_FLAG_PATH, return_value=True)
    def test_publish_of_timing_shortening_draft_enqueues_sweep(self, _revisions, _timing, mock_task):
        flow_id = self._create_flow()
        response = self._patch_actions(flow_id, delay_duration="1d", HTTP_X_POSTHOG_CLIENT="mcp")
        assert response.status_code == 200, response.json()
        staged_at = HogFlow.objects.get(pk=flow_id).draft_updated_at
        assert staged_at is not None
        mock_task.delay.assert_not_called()

        with self.captureOnCommitCallbacks(execute=True):
            publish = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}/publish",
                {"confirm": True, "draft_updated_at": staged_at.isoformat()},
            )

        assert publish.status_code == 200, publish.json()
        mock_task.delay.assert_called_once_with(team_id=self.team.id, hog_flow_id=flow_id, action_ids=["delay_1"])

    @patch(TASK_PATH)
    @patch(TIMING_FLAG_PATH, return_value=True)
    def test_re_enable_sweeps_all_timing_steps(self, _flag, mock_task):
        # Runs parked during a prior active period survive a disable, and timing edits made while
        # disabled never sweep - so the enable transition converges every timing step.
        flow_id = self._create_flow()
        disable = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "draft"})
        assert disable.status_code == 200, disable.json()
        edit = self._patch_actions(flow_id, delay_duration="1d")
        assert edit.status_code == 200, edit.json()
        mock_task.delay.assert_not_called()

        with self.captureOnCommitCallbacks(execute=True):
            enable = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})

        assert enable.status_code == 200, enable.json()
        mock_task.delay.assert_called_once_with(team_id=self.team.id, hog_flow_id=flow_id, action_ids=["delay_1"])

    @patch(TASK_PATH)
    @patch(TIMING_FLAG_PATH, return_value=True)
    def test_graph_operation_shortening_delay_enqueues_sweep(self, _flag, mock_task):
        flow_id = self._create_flow()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/hog_flows/{flow_id}/graph",
                {
                    "operations": [
                        {"op": "update_action", "id": "delay_1", "patch": {"config": {"delay_duration": "1d"}}}
                    ]
                },
            )

        assert response.status_code == 200, response.json()
        mock_task.delay.assert_called_once_with(team_id=self.team.id, hog_flow_id=flow_id, action_ids=["delay_1"])
