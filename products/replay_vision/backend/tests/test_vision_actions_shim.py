from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.integration import Integration

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
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_TEST",
            config={"team": {"name": "Test Workspace"}},
            sensitive_config={"access_token": "test-token"},
            created_by=self.user,
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

    @parameterized.expand(
        [
            ("ordinal_byday", "FREQ=WEEKLY;BYDAY=1MO;BYHOUR=9;BYMINUTE=0"),
            ("weekly_interval", "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO;BYHOUR=9;BYMINUTE=0"),
            ("daily_interval", "FREQ=DAILY;INTERVAL=3;BYHOUR=9;BYMINUTE=0"),
        ]
    )
    def test_rrule_to_cron_rejects_schedules_cron_cannot_express(self, _name: str, rrule: str) -> None:
        with self.assertRaises(ValueError):
            rrule_to_cron(rrule)

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
                    "selection": {"verdict": ["yes"]},
                    "delivery_config": [
                        {"type": "slack", "integration_id": self.integration.id, "channel": "C9|#alerts"}
                    ],
                },
                format="json",
            )
        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["mode"] == "alert"
        assert data["alert_config"]["frequency"] == "every_match"
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).get(id=data["id"])
        assert alert.kind == VisionAlertKind.MATCH
        assert alert.selection == {"verdict": ["yes"]}
        configs = destinations.call_args.args[0]
        assert destinations.call_args.kwargs["alert_id"] == str(alert.id)
        # One destination per match-kind event, all on this team, pointed at the posted channel.
        assert len(configs) == 1
        assert all(config.team.id == self.team.id for config in configs)
        assert "C9" in str(configs[0].payload)
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

    def test_migrated_digest_legacy_id_resolves_to_scout_by_name(self) -> None:
        summary = _scout(skill_name="signals-scout-weekly-abc123", source_id=str(self.scanner.id))
        legacy = VisionAction.objects.unscoped().create(
            team=self.team,
            scanner=self.scanner,
            name="Old digest",
            mode=ActionMode.GROUP_SUMMARY,
            trigger_type=TriggerType.SCHEDULE,
            enabled=False,
            synthesis_config={"migrated_to": summary.skill_name},
        )
        with patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[summary]):
            response = self.client.get(f"{self.base_url}{legacy.id}/")
        assert response.status_code == 200, response.json()
        assert response.json()["id"] == summary.config_id

    def test_malformed_id_is_not_found_rather_than_server_error(self) -> None:
        with patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[]):
            response = self.client.get(f"{self.base_url}not-a-uuid/")
        assert response.status_code == 404

    def test_webhook_url_is_redacted_for_readers(self) -> None:
        summary = _scout(
            source_id=str(self.scanner.id),
            output_destinations={"webhook": {"url": "https://hooks.example.com/t/secret-token?k=v"}},
        )
        with (
            patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[summary]),
            patch(f"{_VIEWSET}.VisionActionViewSet._accessible_scanner_ids", return_value=[str(self.scanner.id)]),
            patch(f"{_VIEWSET}.VisionActionViewSet._can_edit_scanner", return_value=False),
        ):
            response = self.client.get(self.base_url)
        assert response.status_code == 200, response.json()
        url = response.json()["results"][0]["delivery_config"][0]["url"]
        assert url == "https://hooks.example.com/…"
        assert "secret-token" not in url

    def test_scanner_from_another_team_is_rejected(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        foreign_scanner = ReplayScanner.objects.create(
            team=other_team,
            name="Foreign",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "x"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        response = self.client.post(
            self.base_url,
            {
                "name": "Cross team",
                "scanner": str(foreign_scanner.id),
                "mode": "alert",
                "alert_config": {"frequency": "every_match"},
            },
            format="json",
        )
        assert response.status_code == 400, response.json()
        assert VisionAlertConfiguration.objects.for_team(other_team.id).count() == 0

    def test_slack_integration_from_another_team_is_rejected(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other2"), name="Other2")
        foreign = Integration.objects.create(
            team=other_team, kind="slack", integration_id="T_FOREIGN", created_by=self.user
        )
        response = self.client.post(
            self.base_url,
            {
                "name": "Borrowed integration",
                "scanner": str(self.scanner.id),
                "mode": "alert",
                "alert_config": {"frequency": "every_match"},
                "delivery_config": [{"type": "slack", "integration_id": foreign.id, "channel": "C9|#x"}],
            },
            format="json",
        )
        assert response.status_code == 400, response.json()

    def test_non_https_webhook_is_rejected(self) -> None:
        response = self.client.post(
            self.base_url,
            {
                "name": "Cleartext",
                "scanner": str(self.scanner.id),
                "mode": "alert",
                "alert_config": {"frequency": "every_match"},
                "delivery_config": [{"type": "webhook", "url": "http://example.com/hook"}],
            },
            format="json",
        )
        assert response.status_code == 400, response.json()

    def test_list_hides_scanners_the_caller_cannot_access(self) -> None:
        VisionAlertConfiguration.objects.for_team(self.team.id).create(
            team_id=self.team.id, scanner=self.scanner, name="Hidden", kind=VisionAlertKind.MATCH, selection={}
        )
        with (
            patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[]),
            patch(f"{_VIEWSET}.VisionActionViewSet._accessible_scanner_ids", return_value=[]),
        ):
            response = self.client.get(self.base_url)
        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_patch_rebuilds_alert_destinations(self) -> None:
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).create(
            team_id=self.team.id, scanner=self.scanner, name="Rewired", kind=VisionAlertKind.MATCH, selection={}
        )
        with (
            patch(f"{_SHIM}.soft_delete_all_alert_destinations") as soft_delete,
            patch(f"{_SHIM}.create_alert_destination_hog_functions") as create_destinations,
        ):
            response = self.client.patch(
                f"{self.base_url}{alert.id}/",
                {
                    "delivery_config": [
                        {"type": "slack", "integration_id": self.integration.id, "channel": "C_NEW|#moved"}
                    ]
                },
                format="json",
            )
        assert response.status_code == 200, response.json()
        soft_delete.assert_called_once()
        assert "C_NEW" in str(create_destinations.call_args.args[0][0].payload)

    def test_enabled_alert_cap_counts_new_alerts(self) -> None:
        with patch(f"{_SHIM}.MAX_ENABLED_ALERTS_PER_SCANNER", 1):
            VisionAlertConfiguration.objects.for_team(self.team.id).create(
                team_id=self.team.id, scanner=self.scanner, name="First", kind=VisionAlertKind.MATCH, selection={}
            )
            response = self.client.post(
                self.base_url,
                {
                    "name": "Second",
                    "scanner": str(self.scanner.id),
                    "mode": "alert",
                    "alert_config": {"frequency": "every_match"},
                },
                format="json",
            )
        assert response.status_code == 400, response.json()

    def test_scout_patch_refuses_edits_it_cannot_apply(self) -> None:
        summary = _scout(source_id=str(self.scanner.id))
        with patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[summary]):
            response = self.client.patch(
                f"{self.base_url}{summary.config_id}/", {"name": "Renamed digest"}, format="json"
            )
        assert response.status_code == 400, response.json()
        assert "scout" in str(response.json()).lower()

    def test_legacy_id_with_several_successors_updates_and_deletes_all(self) -> None:
        alerts = [
            VisionAlertConfiguration.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                scanner=self.scanner,
                name=f"Fanned {index}",
                kind=VisionAlertKind.MATCH,
                selection={},
            )
            for index in range(2)
        ]
        legacy = VisionAction.objects.unscoped().create(
            team=self.team,
            scanner=self.scanner,
            name="Wide legacy alert",
            mode=ActionMode.ALERT,
            trigger_type=TriggerType.SCHEDULE,
            enabled=False,
            alert_config={"frequency": "every_match", "migrated_to": [str(a.id) for a in alerts]},
        )
        with patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[]):
            response = self.client.patch(f"{self.base_url}{legacy.id}/", {"enabled": False}, format="json")
            assert response.status_code == 200, response.json()
            for alert in alerts:
                alert.refresh_from_db()
                assert alert.enabled is False

            with patch(f"{_SHIM}.soft_delete_all_alert_destinations"):
                response = self.client.delete(f"{self.base_url}{legacy.id}/")
        assert response.status_code == 204
        assert VisionAlertConfiguration.objects.for_team(self.team.id).count() == 0

    def test_fanned_out_alert_checks_every_scanner_not_just_the_first(self) -> None:
        second = ReplayScanner.objects.create(
            team=self.team,
            name="Restricted",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "x"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        alerts = [
            VisionAlertConfiguration.objects.for_team(self.team.id).create(
                team_id=self.team.id, scanner=scanner, name=f"Fan {i}", kind=VisionAlertKind.MATCH, selection={}
            )
            for i, scanner in enumerate((self.scanner, second))
        ]
        legacy = VisionAction.objects.unscoped().create(
            team=self.team,
            scanner=self.scanner,
            name="Wide",
            mode=ActionMode.ALERT,
            trigger_type=TriggerType.SCHEDULE,
            enabled=False,
            alert_config={"frequency": "every_match", "migrated_to": [str(a.id) for a in alerts]},
        )

        # The caller may edit the first successor's scanner but not the second's.
        def only_first(scanner: Any, level: str = "editor", **kwargs: Any) -> bool:
            return getattr(scanner, "id", None) != second.id

        with (
            patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[]),
            patch(
                "products.access_control.backend.facade.user_access_control.UserAccessControl.check_access_level_for_object",
                side_effect=only_first,
            ),
        ):
            response = self.client.delete(f"{self.base_url}{legacy.id}/")
        assert response.status_code == 403, response.status_code
        assert VisionAlertConfiguration.objects.for_team(self.team.id).count() == 2

    def test_frequency_change_is_refused_rather_than_ignored(self) -> None:
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).create(
            team_id=self.team.id, scanner=self.scanner, name="Match", kind=VisionAlertKind.MATCH, selection={}
        )
        response = self.client.patch(
            f"{self.base_url}{alert.id}/",
            {"alert_config": {"frequency": "on_breach", "threshold": 5, "direction": "above"}},
            format="json",
        )
        assert response.status_code == 400, response.json()
        alert.refresh_from_db()
        assert alert.kind == VisionAlertKind.MATCH

    def test_name_of_a_migrated_row_can_be_reused(self) -> None:
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).create(
            team_id=self.team.id, scanner=self.scanner, name="Checkout alerts", kind=VisionAlertKind.MATCH, selection={}
        )
        VisionAction.objects.unscoped().create(
            team=self.team,
            scanner=self.scanner,
            name="Checkout alerts",
            mode=ActionMode.ALERT,
            trigger_type=TriggerType.SCHEDULE,
            enabled=False,
            alert_config={"frequency": "every_match", "migrated_to": [str(alert.id)]},
        )
        with (
            patch(f"{_SHIM}.soft_delete_all_alert_destinations"),
            patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[]),
        ):
            assert self.client.delete(f"{self.base_url}{alert.id}/").status_code == 204
            response = self.client.post(
                self.base_url,
                {
                    "name": "Checkout alerts",
                    "scanner": str(self.scanner.id),
                    "mode": "alert",
                    "alert_config": {"frequency": "every_match"},
                },
                format="json",
            )
        assert response.status_code == 201, response.json()

    def test_child_environment_key_cannot_reach_the_parent_teams_scouts(self) -> None:
        with (
            patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[]),
            patch(
                "products.signals.backend.scout_harness.views.ScoutCanonicalTeamAccessPermission.has_permission",
                return_value=False,
            ),
        ):
            listed = self.client.get(self.base_url)
            created = self.client.post(
                self.base_url,
                {
                    "name": "Sneaky digest",
                    "scanner": str(self.scanner.id),
                    "mode": "group_summary",
                    "trigger_config": {"rrule": "FREQ=DAILY;BYHOUR=8;BYMINUTE=0", "timezone": "UTC"},
                },
                format="json",
            )
        assert listed.status_code == 403, listed.status_code
        assert created.status_code == 403, created.status_code

    def test_rollout_decision_is_evaluated_once_per_request(self) -> None:
        # A flip between the gate in initial() and the handler would serve scouts with the
        # canonical-team gate skipped, so the decision must be made once.
        with patch("posthog.ph_client.feature_enabled_or_false", return_value=True) as flag:
            response = self.client.get(f"{self.base_url}?scanner={self.scanner.id}")
        assert response.status_code == 200, response.json()
        assert flag.call_count == 1

    def test_reenable_runs_the_state_machine(self) -> None:
        from products.replay_vision.backend.models.vision_alert import VisionAlertEvent, VisionAlertState

        alert = VisionAlertConfiguration.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            scanner=self.scanner,
            name="Firing",
            kind=VisionAlertKind.METRIC,
            threshold=1,
            state=VisionAlertState.FIRING,
            consecutive_failures=2,
            selection={},
        )
        assert self.client.patch(f"{self.base_url}{alert.id}/", {"enabled": False}, format="json").status_code == 200
        assert self.client.patch(f"{self.base_url}{alert.id}/", {"enabled": True}, format="json").status_code == 200
        alert.refresh_from_db()
        # A re-enabled alert starts clean; without the state machine it would still be FIRING.
        assert alert.state == VisionAlertState.NOT_FIRING
        assert alert.consecutive_failures == 0
        kinds = set(VisionAlertEvent.objects.filter(alert=alert).values_list("kind", flat=True))
        assert {VisionAlertEvent.Kind.ENABLE, VisionAlertEvent.Kind.DISABLE} <= kinds

    def test_run_on_a_shim_served_row_does_not_crash(self) -> None:
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).create(
            team_id=self.team.id, scanner=self.scanner, name="No run", kind=VisionAlertKind.MATCH, selection={}
        )
        with patch(f"{_SHIM}.signals_facade.list_scouts_for_source", return_value=[]):
            response = self.client.post(f"{self.base_url}{alert.id}/run/", {}, format="json")
        assert response.status_code == 400, response.status_code

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
