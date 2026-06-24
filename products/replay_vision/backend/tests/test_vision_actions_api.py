from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models import Organization, Team
from posthog.models.integration import Integration

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import VisionAction


class _VisionActionAPITestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_patcher = patch(
            "products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_patcher.start()
        self.scanner = self._create_scanner()
        self.integration = self._create_slack_integration()

    def tearDown(self) -> None:
        self.flag_patcher.stop()
        super().tearDown()

    @property
    def actions_url(self) -> str:
        return f"/api/projects/{self.team.id}/vision/actions/"

    def _create_scanner(self, team: Team | None = None, name: str = "my-scanner") -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=team or self.team,
            name=name,
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_FLASH,
        )

    def _create_slack_integration(self, team: Team | None = None) -> Integration:
        return Integration.objects.create(
            team=team or self.team,
            kind="slack",
            integration_id="T_TEST",
            config={"team": {"name": "Test Workspace"}},
            sensitive_config={"access_token": "test-token"},
            created_by=self.user,
        )

    def _create_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": "daily-summary",
            "scanner": str(self.scanner.id),
            "trigger_config": {"rrule": "FREQ=DAILY", "timezone": "UTC"},
            "selection": {"scanner_type": "summarizer", "window_days": 1},
            "synthesis_config": {"prompt_guide": "keep it short"},
            "delivery_config": [
                {"type": "slack", "integration_id": self.integration.id, "channel": "#general"},
            ],
        }
        payload.update(overrides)
        return payload


class TestVisionActionViewSet(_VisionActionAPITestCase):
    def test_create_happy_path(self) -> None:
        resp = self.client.post(self.actions_url, data=self._create_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertEqual(data["name"], "daily-summary")
        self.assertEqual(data["scanner"], str(self.scanner.id))
        self.assertEqual(data["trigger_type"], "schedule")
        self.assertEqual(data["mode"], "group_summary")
        self.assertIsNotNone(data["next_run_at"])
        self.assertIsNone(data["last_run_at"])
        self.assertIsNone(data["hog_flow_id"])
        self.assertEqual(data["created_by"]["id"], self.user.id)

        action = VisionAction.all_teams.get(id=data["id"])
        self.assertEqual(action.team_id, self.team.id)
        self.assertEqual(action.delivery_config[0]["integration_id"], self.integration.id)
        self.assertIsNotNone(action.next_run_at)

    def test_list(self) -> None:
        self.client.post(self.actions_url, data=self._create_payload(), format="json")
        resp = self.client.get(self.actions_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

    def test_actions_flag_off_hides_endpoint(self) -> None:
        # `replay-vision-actions` gates the sub-feature even when product-level `replay-vision` is on.
        def _flags(flag_key: str, *args: Any, **kwargs: Any) -> bool:
            return flag_key != "replay-vision-actions"

        with patch("products.replay_vision.backend.feature_flag.posthoganalytics.feature_enabled", side_effect=_flags):
            list_resp = self.client.get(self.actions_url)
            create_resp = self.client.post(self.actions_url, data=self._create_payload(), format="json")
        self.assertEqual(list_resp.status_code, 404, list_resp.content)
        self.assertEqual(create_resp.status_code, 404, create_resp.content)

    def test_retrieve(self) -> None:
        created = self.client.post(self.actions_url, data=self._create_payload(), format="json").json()
        resp = self.client.get(f"{self.actions_url}{created['id']}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], created["id"])

    def test_patch(self) -> None:
        created = self.client.post(self.actions_url, data=self._create_payload(), format="json").json()
        resp = self.client.patch(
            f"{self.actions_url}{created['id']}/", data={"name": "renamed", "enabled": False}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["name"], "renamed")
        self.assertFalse(resp.json()["enabled"])

    def test_delete(self) -> None:
        created = self.client.post(self.actions_url, data=self._create_payload(), format="json").json()
        resp = self.client.delete(f"{self.actions_url}{created['id']}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(VisionAction.all_teams.filter(id=created["id"]).exists())

    def test_reject_threshold_trigger(self) -> None:
        resp = self.client.post(self.actions_url, data=self._create_payload(trigger_type="threshold"), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("threshold", resp.json()["detail"].lower())

    def test_reject_per_observation_mode(self) -> None:
        resp = self.client.post(self.actions_url, data=self._create_payload(mode="per_observation"), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("per-observation", resp.json()["detail"].lower())

    def test_invalid_rrule(self) -> None:
        resp = self.client.post(
            self.actions_url,
            data=self._create_payload(trigger_config={"rrule": "NOT_A_RULE", "timezone": "UTC"}),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_invalid_timezone(self) -> None:
        # An unknown TZ must be rejected at the API, not blow up later in the scheduling workflow.
        resp = self.client.post(
            self.actions_url,
            data=self._create_payload(trigger_config={"rrule": "FREQ=DAILY", "timezone": "Mars/Phobos"}),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_duplicate_name(self) -> None:
        self.client.post(self.actions_url, data=self._create_payload(), format="json")
        resp = self.client.post(self.actions_url, data=self._create_payload(), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["attr"], "name")

    def test_selection_valid_accepted(self) -> None:
        resp = self.client.post(
            self.actions_url,
            data=self._create_payload(
                selection={"scanner_type": "scorer", "min_score": 0.5, "max_score": 1.0, "tags": ["a", "b"]}
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        action = VisionAction.all_teams.get(id=resp.json()["id"])
        self.assertEqual(action.selection["min_score"], 0.5)

    def test_selection_unknown_key_ignored(self) -> None:
        # The typed SelectionSerializer is the allowlist; unknown keys are dropped, not persisted.
        resp = self.client.post(
            self.actions_url,
            data=self._create_payload(selection={"scanner_type": "summarizer", "bogus_key": "x"}),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        action = VisionAction.all_teams.get(id=resp.json()["id"])
        self.assertNotIn("bogus_key", action.selection)


class TestVisionActionCrossTeamIDOR(_VisionActionAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.other_org = Organization.objects.create(name="other-org")
        self.other_team = Team.objects.create(organization=self.other_org, name="other-team")
        self.other_scanner = self._create_scanner(team=self.other_team, name="other-scanner")
        self.other_integration = self._create_slack_integration(team=self.other_team)
        self.other_action = VisionAction.all_teams.create(
            team=self.other_team,
            scanner=self.other_scanner,
            name="other-action",
        )

    def test_cannot_retrieve_other_team_action(self) -> None:
        resp = self.client.get(f"{self.actions_url}{self.other_action.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_cannot_patch_other_team_action(self) -> None:
        resp = self.client.patch(f"{self.actions_url}{self.other_action.id}/", data={"name": "hijack"}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_cannot_delete_other_team_action(self) -> None:
        resp = self.client.delete(f"{self.actions_url}{self.other_action.id}/")
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(VisionAction.all_teams.filter(id=self.other_action.id).exists())

    def test_cannot_bind_other_team_scanner(self) -> None:
        resp = self.client.post(
            self.actions_url, data=self._create_payload(scanner=str(self.other_scanner.id)), format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_cannot_reference_other_team_integration(self) -> None:
        resp = self.client.post(
            self.actions_url,
            data=self._create_payload(
                delivery_config=[{"type": "slack", "integration_id": self.other_integration.id, "channel": "#x"}]
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
