from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models import Team
from posthog.models.integration import Integration

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.replay_vision.backend.api.delivery import EVENT_NAME
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import VisionAction


class TestVisionActionDelivery(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_template_to_db(template_slack)
        self.flag_patcher = patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_patcher.start()
        # Saving a HogFunction pushes it to the CDP workers; there are none in tests.
        self.reload_patcher = patch(
            "products.cdp.backend.models.hog_functions.hog_function.reload_hog_functions_on_workers",
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

    def _destinations(self, action: VisionAction) -> list[HogFunction]:
        """The action's live internal_destination HogFunctions — found by the vision_action_id filter
        (no FK; the trigger filter is the binding), mirroring delivery._managed_destinations."""
        return list(
            HogFunction.objects.filter(
                team_id=self.team.id,
                type="internal_destination",
                deleted=False,
                filters__contains={"properties": [{"key": "vision_action_id", "value": str(action.id)}]},
            ).order_by("created_at")
        )

    @staticmethod
    def _inputs(fn: HogFunction) -> dict[str, Any]:
        assert fn.inputs is not None
        return fn.inputs

    @staticmethod
    def _filters(fn: HogFunction) -> dict[str, Any]:
        assert fn.filters is not None
        return fn.filters

    def test_create_provisions_destination(self) -> None:
        action = self._create_action()

        destinations = self._destinations(action)
        self.assertEqual(len(destinations), 1)
        fn = destinations[0]
        self.assertEqual(fn.type, "internal_destination")
        self.assertEqual(fn.template_id, "template-slack")
        self.assertTrue(fn.enabled)
        self.assertEqual(fn.name, "Replay Vision · daily-summary")

        event_filter = self._filters(fn)["events"][0]
        self.assertEqual(event_filter["id"], EVENT_NAME)
        prop = self._filters(fn)["properties"][0]
        self.assertEqual(prop["key"], "vision_action_id")
        self.assertEqual(prop["value"], str(action.id))

        self.assertEqual(self._inputs(fn)["slack_workspace"]["value"], self.integration.id)
        self.assertEqual(self._inputs(fn)["channel"]["value"], "#general")
        self.assertEqual(self._inputs(fn)["text"]["value"], "{event.properties.slack_text}")

    def test_channel_composite_is_stripped_to_bare_id_for_slack(self) -> None:
        # The UI stores the `${id}|#${name}` picker composite; the Slack destination must receive the
        # bare id, or the channel input is malformed and delivery fails.
        action = self._create_action(
            delivery_config=[{"type": "slack", "integration_id": self.integration.id, "channel": "C123|#general"}],
        )
        self.assertEqual(self._inputs(self._destinations(action)[0])["channel"]["value"], "C123")

    def test_create_two_targets_makes_two_destinations(self) -> None:
        action = self._create_action(
            delivery_config=[
                {"type": "slack", "integration_id": self.integration.id, "channel": "#one"},
                {"type": "slack", "integration_id": self.other_integration.id, "channel": "#two"},
            ],
        )
        destinations = self._destinations(action)
        self.assertEqual(len(destinations), 2)
        self.assertEqual({self._inputs(d)["channel"]["value"] for d in destinations}, {"#one", "#two"})

    def test_create_empty_delivery_no_destination(self) -> None:
        action = self._create_action(delivery_config=[])
        self.assertEqual(self._destinations(action), [])

    def test_update_delivery_reprovisions(self) -> None:
        action = self._create_action()
        resp = self.client.patch(
            f"{self.actions_url}{action.id}/",
            data={"delivery_config": [{"type": "slack", "integration_id": self.integration.id, "channel": "#changed"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        destinations = self._destinations(action)
        self.assertEqual(len(destinations), 1)
        self.assertEqual(self._inputs(destinations[0])["channel"]["value"], "#changed")

    @parameterized.expand(
        [
            ("selection", {"selection": {"window_days": 7}}),
            ("trigger_config", {"trigger_config": {"rrule": "FREQ=WEEKLY", "timezone": "UTC"}}),
            ("synthesis_config", {"synthesis_config": {"prompt_guide": "focus on checkout drop-off"}}),
        ]
    )
    def test_update_non_delivery_does_not_reprovision(self, _field: str, patch_data: dict[str, Any]) -> None:
        action = self._create_action()
        before = self._destinations(action)[0].id

        # Editing a field the destinations don't reflect (cadence/selection/synthesis) must not churn them.
        with patch("products.replay_vision.backend.api.vision_actions.provision_delivery") as mock_provision:
            resp = self.client.patch(f"{self.actions_url}{action.id}/", data=patch_data, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        mock_provision.assert_not_called()

        after = self._destinations(action)
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0].id, before)

    def test_rename_reprovisions_and_updates_destination_name(self) -> None:
        # Each destination is named after the action, so a rename re-provisions to keep the name in sync.
        action = self._create_action()
        resp = self.client.patch(f"{self.actions_url}{action.id}/", data={"name": "renamed action"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)

        destinations = self._destinations(action)
        self.assertEqual(len(destinations), 1)
        self.assertEqual(destinations[0].name, "Replay Vision · renamed action")

    def test_disable_archives_destinations(self) -> None:
        action = self._create_action()
        resp = self.client.patch(f"{self.actions_url}{action.id}/", data={"enabled": False}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._destinations(action), [])

    def test_delete_archives_destinations(self) -> None:
        action = self._create_action()
        resp = self.client.delete(f"{self.actions_url}{action.id}/")
        self.assertEqual(resp.status_code, 204, resp.content)
        self.assertEqual(self._destinations(action), [])

    def test_update_to_empty_delivery_archives_destinations(self) -> None:
        action = self._create_action()
        resp = self.client.patch(f"{self.actions_url}{action.id}/", data={"delivery_config": []}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._destinations(action), [])
