from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.replay_vision.backend.api.vision_actions_shim import cron_to_rrule, rrule_to_cron
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import ActionMode, TriggerType, VisionAction
from products.replay_vision.backend.models.vision_alert import VisionAlertConfiguration, VisionAlertKind
from products.signals.backend.facade.api import ScoutSummary

_SHIM = "products.replay_vision.backend.api.vision_actions_shim"
_VIEWSET = "products.replay_vision.backend.api.vision_actions"


def _scout(config_id: str = "01a00000-0000-7000-8000-000000000abc", **overrides: Any) -> ScoutSummary:
    fields: dict[str, Any] = {
        "config_id": config_id,
        "skill_name": "signals-scout-daily-roundup",
        "source_id": None,
        "enabled": True,
        "run_cron_schedule": "0 9 * * 1",
        "run_interval_minutes": 1440,
        "output_destinations": {"slack": {"integration_id": 7, "channel_id": "C9", "channel_name": "#digests"}},
        "description": "Weekly roundup",
        "created_at": datetime(2026, 8, 1, tzinfo=UTC),
        "created_by_id": None,
        "last_run_at": None,
    }
    fields.update(overrides)
    return ScoutSummary(**fields)


class TestVisionActionsShim(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Checkout monitor",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "watch checkout"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        self.base_url = f"/api/projects/{self.team.id}/vision/actions/"
        self._flag = patch("posthog.ph_client.feature_enabled_or_false", return_value=True)
        self._flag.start()
        self.addCleanup(self._flag.stop)

    @parameterized.expand(
        [
            ("weekly", "FREQ=WEEKLY;BYDAY=MO,FR;BYHOUR=9;BYMINUTE=30"),
            ("daily", "FREQ=DAILY;BYHOUR=8;BYMINUTE=0"),
            ("hourly", "FREQ=HOURLY"),
            ("minutely", "FREQ=MINUTELY;INTERVAL=15"),
        ]
    )
    def test_cron_rrule_round_trip(self, _name: str, rrule: str) -> None:
        assert cron_to_rrule(rrule_to_cron(rrule)) == rrule

    def test_flagged_alert_create_lands_in_new_system(self) -> None:
        with patch(f"{_SHIM}.create_alert_destination_hog_functions") as destinations:
            response = self.client.post(
                self.base_url,
                {
                    "name": "Failed checkouts",
                    "scanner": str(self.scanner.id),
                    "mode": "alert",
                    "trigger_type": "schedule",
                    "trigger_config": {"rrule": "FREQ=DAILY;BYHOUR=8;BYMINUTE=0", "timezone": "UTC"},
                    "alert_config": {"frequency": "every_match", "metric": "count"},
                    "selection": {"verdict": ["fail"]},
                    "delivery_config": [{"type": "slack", "integration_id": 7, "channel": "C9|#alerts"}],
                },
                format="json",
            )
        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["mode"] == "alert"
        assert data["alert_config"]["frequency"] == "every_match"
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).get(id=data["id"])
        assert alert.kind == VisionAlertKind.MATCH
        assert alert.selection == {"verdict": ["fail"]}
        destinations.assert_called_once()
        assert VisionAction.objects.unscoped().filter(team=self.team).count() == 0

    def test_flagged_on_breach_create_maps_to_metric(self) -> None:
        with patch(f"{_SHIM}.create_alert_destination_hog_functions"):
            response = self.client.post(
                self.base_url,
                {
                    "name": "Too many fails",
                    "scanner": str(self.scanner.id),
                    "mode": "alert",
                    "alert_config": {
                        "frequency": "on_breach",
                        "metric": "count",
                        "direction": "above",
                        "threshold": 5,
                        "window_days": 7,
                    },
                },
                format="json",
            )
        assert response.status_code == 201, response.json()
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).get()
        assert alert.kind == VisionAlertKind.METRIC
        assert alert.threshold == 5.0
        assert alert.window_days == 7

    def test_flagged_digest_create_becomes_scout(self) -> None:
        created = _scout(skill_name="signals-scout-daily-digest", source_id=str(self.scanner.id))
        with (
            patch(
                f"{_SHIM}.signals_facade.create_scout_for_source",
                return_value=type("R", (), {"config": type("C", (), {"id": created.config_id})(), "created": True})(),
            ) as create_scout,
            patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[created]),
        ):
            response = self.client.post(
                self.base_url,
                {
                    "name": "Daily digest",
                    "scanner": str(self.scanner.id),
                    "mode": "group_summary",
                    "trigger_config": {"rrule": "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0", "timezone": "UTC"},
                    "synthesis_config": {"prompt_guide": "Focus on payments."},
                },
                format="json",
            )
        assert response.status_code == 201, response.json()
        kwargs = create_scout.call_args.kwargs
        assert kwargs["config_options"]["run_cron_schedule"] == "0 9 * * 1"
        assert "Focus on payments." in kwargs["body"]
        assert response.json()["mode"] == "group_summary"
        assert VisionAction.objects.unscoped().filter(team=self.team).count() == 0

    def test_flagged_list_synthesizes_both_systems(self) -> None:
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            scanner=self.scanner,
            name="Match alert",
            kind=VisionAlertKind.MATCH,
            selection={},
        )
        with patch(
            f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[_scout(source_id=str(self.scanner.id))]
        ):
            response = self.client.get(self.base_url)
        assert response.status_code == 200
        results = response.json()["results"]
        modes = {row["mode"] for row in results}
        assert modes == {"alert", "group_summary"}
        alert_row = next(row for row in results if row["mode"] == "alert")
        assert alert_row["id"] == str(alert.id)
        digest_row = next(row for row in results if row["mode"] == "group_summary")
        assert digest_row["trigger_config"]["rrule"] == "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0"
        assert digest_row["delivery_config"] == [{"type": "slack", "integration_id": 7, "channel": "C9|#digests"}]

    def test_migrated_legacy_id_resolves_to_new_alert(self) -> None:
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).create(
            team_id=self.team.id, scanner=self.scanner, name="Successor", kind=VisionAlertKind.MATCH, selection={}
        )
        legacy = VisionAction.objects.unscoped().create(
            team=self.team,
            scanner=self.scanner,
            name="Old alert",
            mode=ActionMode.ALERT,
            trigger_type=TriggerType.SCHEDULE,
            enabled=False,
            alert_config={"frequency": "every_match", "migrated_to": [str(alert.id)]},
        )
        with patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[]):
            response = self.client.get(f"{self.base_url}{legacy.id}/")
        assert response.status_code == 200
        assert response.json()["id"] == str(alert.id)

    def test_flagged_update_and_destroy_operate_on_new_alert(self) -> None:
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            scanner=self.scanner,
            name="Metric alert",
            kind=VisionAlertKind.METRIC,
            threshold=5,
            selection={},
        )
        response = self.client.patch(
            f"{self.base_url}{alert.id}/", {"alert_config": {"threshold": 9}, "enabled": False}, format="json"
        )
        assert response.status_code == 200, response.json()
        alert.refresh_from_db()
        assert alert.threshold == 9
        assert alert.enabled is False

        with patch(f"{_SHIM}.soft_delete_all_alert_destinations") as soft_delete:
            response = self.client.delete(f"{self.base_url}{alert.id}/")
        assert response.status_code == 204
        soft_delete.assert_called_once()
        assert not VisionAlertConfiguration.objects.for_team(self.team.id).filter(id=alert.id).exists()

    def test_flagged_scout_destroy_goes_through_facade(self) -> None:
        summary = _scout(source_id=str(self.scanner.id))
        with (
            patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[summary]),
            patch(f"{_SHIM}.signals_facade.delete_scout_for_source", return_value=True) as delete_scout,
        ):
            response = self.client.delete(f"{self.base_url}{summary.config_id}/")
        assert response.status_code == 204
        assert delete_scout.call_args.kwargs["config_id"] == summary.config_id

    def test_unflagged_requests_keep_legacy_behavior(self) -> None:
        self._flag.stop()
        with patch("posthog.ph_client.feature_enabled_or_false", return_value=False):
            response = self.client.post(
                self.base_url,
                {
                    "name": "Legacy digest",
                    "scanner": str(self.scanner.id),
                    "mode": "group_summary",
                    "trigger_type": "schedule",
                    "trigger_config": {"rrule": "FREQ=DAILY;BYHOUR=8;BYMINUTE=0", "timezone": "UTC"},
                },
                format="json",
            )
        self._flag.start()
        assert response.status_code == 201, response.json()
        assert VisionAction.objects.unscoped().filter(team=self.team, name="Legacy digest").exists()
