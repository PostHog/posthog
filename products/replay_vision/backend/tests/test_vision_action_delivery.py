from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models import Team
from posthog.models.integration import Integration

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.replay_vision.backend.api.delivery import EVENT_NAME, provision_delivery
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import VisionAction

# The webhook template is defined in the nodejs registry (no Python source object like Slack's). The
# serializer only needs the row to resolve by id and expose its inputs schema, so a minimal stand-in
# with the same inputs is enough to exercise provisioning.
_WEBHOOK_TEMPLATE = {
    "id": "template-webhook",
    "name": "HTTP Webhook",
    "description": "Sends a webhook templated by the incoming event data",
    "type": "destination",
    "status": "stable",
    "free": False,
    "category": ["Custom"],
    "code_language": "hog",
    "code": "let res := fetch(inputs.url, {'method': inputs.method, 'headers': inputs.headers, 'body': inputs.body})",
    "inputs_schema": [
        {"key": "url", "type": "string", "label": "Webhook URL", "required": True},
        {"key": "method", "type": "string", "label": "Method", "required": False},
        {"key": "body", "type": "json", "label": "JSON Body", "required": False},
        {"key": "headers", "type": "dictionary", "label": "Headers", "required": False},
    ],
}


class TestVisionActionDelivery(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_template_to_db(template_slack)
        sync_template_to_db(_WEBHOOK_TEMPLATE)
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
            model=ScannerModel.GEMINI_3_6_FLASH,
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

    def _request(self) -> Request:
        # provision_delivery threads a DRF Request into HogFunctionSerializer, which reads request.user.
        drf_request = Request(APIRequestFactory().post("/"))
        drf_request.user = self.user
        return cast(Request, drf_request)

    def _provision_action(self, delivery_config: list[dict[str, Any]]) -> VisionAction:
        """Create an action with delivery_config set on the model and provision it directly, bypassing
        the API serializer so a delivery type's provisioning can be exercised independently of the
        serializer that gates which types the API accepts."""
        action = VisionAction(
            team=self.team,
            scanner=self.scanner,
            name=f"provisioned-{VisionAction.all_teams.count()}",
            trigger_config={"rrule": "FREQ=DAILY", "timezone": "UTC"},
            delivery_config=delivery_config,
        )
        action.save()
        provision_delivery(action, request=self._request(), team=self.team)
        return action

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
        # A whole-string template on the json blocks input resolves to the raw list at delivery time,
        # so the pre-split report renders as one message instead of Slack splitting the text mid-link.
        self.assertEqual(self._inputs(fn)["blocks"]["value"], "{event.properties.slack_blocks}")

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

    def test_webhook_target_provisions_webhook_destination(self) -> None:
        # A webhook target must resolve to the template-webhook destination with the URL, a POST, the
        # versioned header, and a body that references the emitted event's structured props — otherwise
        # the webhook fires with a malformed/empty payload.
        action = self._provision_action([{"type": "webhook", "url": "https://example.com/hook"}])

        destinations = self._destinations(action)
        self.assertEqual(len(destinations), 1)
        fn = destinations[0]
        self.assertEqual(fn.template_id, "template-webhook")
        inputs = self._inputs(fn)
        self.assertEqual(inputs["url"]["value"], "https://example.com/hook")
        self.assertEqual(inputs["method"]["value"], "POST")
        self.assertEqual(inputs["headers"]["value"]["X-PostHog-Webhook-Version"], "1")
        body = inputs["body"]["value"]
        self.assertEqual(body["type"], "replay_vision.{event.properties.event_kind}")
        self.assertEqual(body["data"]["report"], "{event.properties.report_markdown}")
        self.assertEqual(body["data"]["run_url"], "{event.properties.run_url}")
        # The trigger filter still binds the destination to this action (the same bind-by-filter as Slack).
        self.assertEqual(self._filters(fn)["properties"][0]["value"], str(action.id))

    def test_mixed_slack_and_webhook_targets(self) -> None:
        action = self._provision_action(
            [
                {"type": "slack", "integration_id": self.integration.id, "channel": "C1|#general"},
                {"type": "webhook", "url": "https://example.com/hook"},
            ]
        )
        by_template = {fn.template_id for fn in self._destinations(action)}
        self.assertEqual(by_template, {"template-slack", "template-webhook"})

    def test_reprovision_switches_slack_to_webhook(self) -> None:
        # Reconcile is archive-and-recreate: switching a target's type must drop the stale Slack
        # destination and stand up the webhook one, not leave both firing.
        action = self._provision_action([{"type": "slack", "integration_id": self.integration.id, "channel": "#a"}])
        self.assertEqual([d.template_id for d in self._destinations(action)], ["template-slack"])

        action.delivery_config = [{"type": "webhook", "url": "https://example.com/hook"}]
        action.save(update_fields=["delivery_config"])
        provision_delivery(action, request=self._request(), team=self.team)

        self.assertEqual([d.template_id for d in self._destinations(action)], ["template-webhook"])
