from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models import Team
from posthog.models.integration import Integration

from products.replay_vision.backend.api.delivery import EVENT_NAME
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import VisionAction
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class TestVisionActionDelivery(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_template_to_db(template_slack)
        self.flag_patcher = patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_patcher.start()
        # The post_save hook pushes flows to workers; there are none in tests.
        self.reload_patcher = patch(
            "products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers",
        )
        self.reload_patcher.start()
        self.scanner = self._create_scanner()
        self.integration = self._create_slack_integration()
        self.other_integration = self._create_slack_integration()

    def tearDown(self) -> None:
        self.reload_patcher.stop()
        self.flag_patcher.stop()
        super().tearDown()

    @property
    def actions_url(self) -> str:
        return f"/api/projects/{self.team.id}/vision/actions/"

    def _create_scanner(self, team: Team | None = None) -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=team or self.team,
            name="my-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_FLASH,
        )

    def _create_slack_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id=f"T_{Integration.objects.count()}",
            config={"team": {"name": "Test Workspace"}},
            sensitive_config={"access_token": "test-token"},
            created_by=self.user,
        )

    def _payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": "daily-summary",
            "scanner": str(self.scanner.id),
            "trigger_config": {"rrule": "FREQ=DAILY", "timezone": "UTC"},
            "selection": {"scanner_type": "summarizer", "window_days": 1},
            "delivery_config": [
                {"type": "slack", "integration_id": self.integration.id, "channel": "#general"},
            ],
        }
        payload.update(overrides)
        return payload

    def _create_action(self, **overrides: Any) -> VisionAction:
        resp = self.client.post(self.actions_url, data=self._payload(**overrides), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        return VisionAction.all_teams.get(id=resp.json()["id"])

    def _trigger_event_filter(self, flow: HogFlow) -> dict[str, Any]:
        trigger = next(a for a in flow.actions if a["type"] == "trigger")
        return trigger["config"]["filters"]["events"][0]

    def _slack_nodes(self, flow: HogFlow) -> list[dict[str, Any]]:
        return [a for a in flow.actions if a["type"] == "function"]

    def test_create_provisions_flow(self) -> None:
        action = self._create_action()
        self.assertIsNotNone(action.hog_flow_id)

        flow = HogFlow.objects.get(id=action.hog_flow_id)
        self.assertEqual(flow.status, "active")
        self.assertEqual(flow.name, "Replay Vision · daily-summary")

        event_filter = self._trigger_event_filter(flow)
        self.assertEqual(event_filter["id"], EVENT_NAME)
        self.assertEqual(event_filter["properties"][0]["key"], "vision_action_id")
        self.assertEqual(event_filter["properties"][0]["value"], [str(action.id)])

        slack_nodes = self._slack_nodes(flow)
        self.assertEqual(len(slack_nodes), 1)
        inputs = slack_nodes[0]["config"]["inputs"]
        self.assertEqual(inputs["slack_workspace"]["value"], self.integration.id)
        self.assertEqual(inputs["channel"]["value"], "#general")
        self.assertEqual(inputs["text"]["value"], "{event.properties.slack_text}")

    def test_create_two_targets_chained(self) -> None:
        action = self._create_action(
            delivery_config=[
                {"type": "slack", "integration_id": self.integration.id, "channel": "#one"},
                {"type": "slack", "integration_id": self.other_integration.id, "channel": "#two"},
            ],
        )
        flow = HogFlow.objects.get(id=action.hog_flow_id)
        slack_nodes = self._slack_nodes(flow)
        self.assertEqual(len(slack_nodes), 2)

        # Chained trigger -> slack_0 -> slack_1 -> exit_node.
        edge_map = {e["from"]: e["to"] for e in flow.edges}
        self.assertEqual(edge_map["trigger_node"], "slack_0")
        self.assertEqual(edge_map["slack_0"], "slack_1")
        self.assertEqual(edge_map["slack_1"], "exit_node")

    def test_create_empty_delivery_no_flow(self) -> None:
        action = self._create_action(delivery_config=[])
        self.assertIsNone(action.hog_flow_id)
        self.assertEqual(HogFlow.objects.count(), 0)

    def test_update_delivery_reprovisions_same_flow(self) -> None:
        action = self._create_action()
        flow_id = action.hog_flow_id

        resp = self.client.patch(
            f"{self.actions_url}{action.id}/",
            data={"delivery_config": [{"type": "slack", "integration_id": self.integration.id, "channel": "#changed"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        action.refresh_from_db()
        self.assertEqual(action.hog_flow_id, flow_id)
        flow = HogFlow.objects.get(id=flow_id)
        self.assertEqual(self._slack_nodes(flow)[0]["config"]["inputs"]["channel"]["value"], "#changed")

    def test_update_non_delivery_does_not_reprovision(self) -> None:
        action = self._create_action()
        flow_before = HogFlow.objects.get(id=action.hog_flow_id)

        with patch("products.replay_vision.backend.api.vision_actions.provision_delivery_flow") as mock_provision:
            resp = self.client.patch(
                f"{self.actions_url}{action.id}/",
                data={"name": "renamed", "selection": {"window_days": 7}},
                format="json",
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        mock_provision.assert_not_called()

        flow_after = HogFlow.objects.get(id=action.hog_flow_id)
        self.assertEqual(flow_after.updated_at, flow_before.updated_at)
        self.assertEqual(flow_after.version, flow_before.version)

    def test_disable_archives_flow(self) -> None:
        action = self._create_action()
        flow_id = action.hog_flow_id

        resp = self.client.patch(f"{self.actions_url}{action.id}/", data={"enabled": False}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)

        flow = HogFlow.objects.get(id=flow_id)
        self.assertEqual(flow.status, "archived")

    def test_delete_archives_flow(self) -> None:
        action = self._create_action()
        flow_id = action.hog_flow_id

        resp = self.client.delete(f"{self.actions_url}{action.id}/")
        self.assertEqual(resp.status_code, 204, resp.content)

        flow = HogFlow.objects.get(id=flow_id)
        self.assertEqual(flow.status, "archived")
