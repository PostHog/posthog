from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.replay_vision.backend.management.commands.migrate_vision_actions import rrule_to_cron
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import ActionMode, TriggerType, VisionAction
from products.replay_vision.backend.models.vision_alert import VisionAlertConfiguration, VisionAlertKind

_CMD = "products.replay_vision.backend.management.commands.migrate_vision_actions"


class TestMigrateVisionActions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Checkout monitor",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "watch checkout"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        for key in ("replay-vision-alerts", "replay-vision-scout-digests"):
            FeatureFlag.objects.create(
                team=self.team,
                key=key,
                created_by=self.user,
                filters={
                    "aggregation_group_type_index": 0,
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "$group_key",
                                    "type": "group",
                                    "group_type_index": 0,
                                    "value": [],
                                    "operator": "exact",
                                }
                            ],
                            "rollout_percentage": 100,
                        }
                    ],
                },
            )

    def _make_scanner(self, name: str) -> ReplayScanner:
        return ReplayScanner.objects.create(
            team=self.team,
            name=name,
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "watch"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )

    def _make_action(self, **overrides: Any) -> VisionAction:
        fields: dict[str, Any] = {
            "team": self.team,
            "scanner": self.scanner,
            "name": f"Legacy {VisionAction.objects.unscoped().count()}",
            "mode": ActionMode.ALERT,
            "trigger_type": TriggerType.SCHEDULE,
            "trigger_config": {"rrule": "FREQ=DAILY;BYHOUR=8;BYMINUTE=0", "timezone": "UTC"},
            "created_by": self.user,
            "enabled": True,
        }
        fields.update(overrides)
        return VisionAction.objects.unscoped().create(**fields)

    def _run(self, execute: bool = True) -> None:
        args = ["--flag-team-id", str(self.team.id)]
        if execute:
            args.append("--execute")
        call_command("migrate_vision_actions", *args)

    @parameterized.expand(
        [
            ("daily", "FREQ=DAILY;BYHOUR=9;BYMINUTE=30", "30 9 * * *"),
            ("weekly_days", "FREQ=WEEKLY;BYDAY=MO,FR;BYHOUR=8;BYMINUTE=0", "0 8 * * 1,5"),
            ("weekly_bare", "FREQ=WEEKLY;BYHOUR=8;BYMINUTE=0", "0 8 * * 1"),
            ("hourly", "FREQ=HOURLY", "0 * * * *"),
            ("minutely_floored", "FREQ=MINUTELY;INTERVAL=5", "*/15 * * * *"),
            ("daily_bare", "FREQ=DAILY", "0 8 * * *"),
        ]
    )
    def test_rrule_to_cron(self, _name: str, rrule: str, expected: str) -> None:
        assert rrule_to_cron(rrule) == expected

    def test_rrule_to_cron_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            rrule_to_cron("FREQ=MONTHLY;BYMONTHDAY=1")

    def test_every_match_becomes_match_alert_with_destination(self) -> None:
        action = self._make_action(
            alert_config={"frequency": "every_match", "metric": "count"},
            selection={"verdict": ["fail"], "scanner_ids": None},
            delivery_config=[{"type": "slack", "integration_id": 7, "channel": "C123|#alerts"}],
        )
        with patch(f"{_CMD}.Command._create_destinations") as destinations:
            self._run()
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).get()
        assert alert.kind == VisionAlertKind.MATCH
        assert alert.threshold is None
        assert alert.selection == {"verdict": ["fail"]}
        assert alert.enabled is True
        destinations.assert_called_once()
        action.refresh_from_db()
        assert action.enabled is False
        assert action.alert_config["migrated_to"] == [str(alert.id)]

    def test_on_breach_becomes_metric_alert_with_snapped_window(self) -> None:
        self._make_action(
            alert_config={
                "frequency": "on_breach",
                "metric": "count",
                "direction": "above",
                "threshold": 5,
                "window_days": 10,
            },
            trigger_config={"rrule": "FREQ=HOURLY", "timezone": "UTC"},
        )
        with patch(f"{_CMD}.Command._create_destinations"):
            self._run()
        alert = VisionAlertConfiguration.objects.for_team(self.team.id).get()
        assert alert.kind == VisionAlertKind.METRIC
        assert alert.threshold == 5.0
        assert alert.window_days in (7, 14)
        assert alert.check_interval_minutes == 60

    def test_scanner_ids_split_into_one_alert_each(self) -> None:
        other = ReplayScanner.objects.create(
            team=self.team,
            name="Second",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "x"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        self._make_action(
            name="Wide alert",
            alert_config={"frequency": "every_match"},
            selection={"scanner_ids": [str(self.scanner.id), str(other.id)]},
        )
        with patch(f"{_CMD}.Command._create_destinations"):
            self._run()
        alerts = VisionAlertConfiguration.objects.for_team(self.team.id)
        assert alerts.count() == 2
        assert {a.scanner_id for a in alerts} == {self.scanner.id, other.id}

    def test_custom_digest_becomes_scout(self) -> None:
        action = self._make_action(
            name="Weekly checkout roundup",
            mode=ActionMode.GROUP_SUMMARY,
            is_scanner_digest=False,
            trigger_config={"rrule": "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0", "timezone": "UTC"},
            selection={"verdict": ["fail"], "window_days": 7},
            synthesis_config={"prompt_guide": "Focus on payment failures."},
            delivery_config=[{"type": "slack", "integration_id": 7, "channel": "C123|#digests"}],
        )
        with patch("products.signals.backend.facade.api.create_scout_for_source") as create_scout:
            self._run()
        assert create_scout.call_count == 1
        kwargs = create_scout.call_args.kwargs
        assert kwargs["name"].startswith("signals-scout-weekly-checkout-roundup-")
        assert kwargs["source_id"] == str(self.scanner.id)
        assert "Focus on payment failures." in kwargs["body"]
        assert "verdict in ['fail']" in kwargs["body"]
        assert kwargs["config_options"]["run_cron_schedule"] == "0 9 * * 1"
        assert kwargs["config_options"]["output_destinations"]["slack"]["channel_id"] == "C123"
        action.refresh_from_db()
        assert action.enabled is False
        assert action.synthesis_config["migrated_to"] == kwargs["name"]

    def test_deliveryless_default_is_retired_not_migrated(self) -> None:
        action = self._make_action(
            mode=ActionMode.GROUP_SUMMARY, is_scanner_digest=True, delivery_config=[], synthesis_config={}
        )
        with patch("products.signals.backend.facade.api.create_scout_for_source") as create_scout:
            self._run()
        create_scout.assert_not_called()
        action.refresh_from_db()
        assert action.enabled is False
        assert action.synthesis_config == {"retired": True}
        assert VisionAlertConfiguration.objects.for_team(self.team.id).count() == 0

    def test_org_with_only_default_digests_is_still_flagged(self) -> None:
        # One default digest per scanner: the unique constraint allows no more.
        for index in range(2):
            scanner = self.scanner if index == 0 else self._make_scanner(f"Scanner {index}")
            self._make_action(
                scanner=scanner,
                mode=ActionMode.GROUP_SUMMARY,
                is_scanner_digest=True,
                delivery_config=[],
                synthesis_config={},
            )
        with patch("products.signals.backend.facade.api.create_scout_for_source") as create_scout:
            self._run()
        create_scout.assert_not_called()
        for key in ("replay-vision-alerts", "replay-vision-scout-digests"):
            flag = FeatureFlag.objects.get(team=self.team, key=key)
            assert flag.filters["groups"][0]["properties"][0]["value"] == [str(self.team.organization_id)]

    def test_one_unconvertible_row_blocks_its_whole_org(self) -> None:
        good = self._make_action(alert_config={"frequency": "every_match"})
        bad = self._make_action(
            name="Fortnightly digest",
            mode=ActionMode.GROUP_SUMMARY,
            is_scanner_digest=False,
            # cron cannot express a fortnightly cadence, so this row cannot migrate.
            trigger_config={"rrule": "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO;BYHOUR=9;BYMINUTE=0", "timezone": "UTC"},
        )
        with (
            patch(f"{_CMD}.Command._create_destinations"),
            patch("products.signals.backend.facade.api.create_scout_for_source") as create_scout,
        ):
            # The run reports the blocked rows and exits non-zero so an operator sees them.
            with self.assertRaises(CommandError):
                self._run()
        create_scout.assert_not_called()
        # Nothing moved: the good row is untouched rather than half-migrating the org.
        assert VisionAlertConfiguration.objects.for_team(self.team.id).count() == 0
        for action in (good, bad):
            action.refresh_from_db()
            assert action.enabled is True
        flag = FeatureFlag.objects.get(team=self.team, key="replay-vision-alerts")
        assert flag.filters["groups"][0]["properties"][0]["value"] == []

    def test_rerun_skips_migrated_rows(self) -> None:
        self._make_action(alert_config={"frequency": "every_match"})
        with patch(f"{_CMD}.Command._create_destinations"):
            self._run()
            self._run()
        assert VisionAlertConfiguration.objects.for_team(self.team.id).count() == 1

    def test_org_appended_to_both_flags_once(self) -> None:
        self._make_action(alert_config={"frequency": "every_match"})
        with patch(f"{_CMD}.Command._create_destinations"):
            self._run()
            self._run()
        for key in ("replay-vision-alerts", "replay-vision-scout-digests"):
            flag = FeatureFlag.objects.get(team=self.team, key=key)
            values = flag.filters["groups"][0]["properties"][0]["value"]
            assert values == [str(self.team.organization_id)]

    def test_dry_run_changes_nothing(self) -> None:
        action = self._make_action(alert_config={"frequency": "every_match"})
        with patch(f"{_CMD}.Command._create_destinations"):
            self._run(execute=False)
        action.refresh_from_db()
        assert action.enabled is True
        assert "migrated_to" not in action.alert_config
        assert VisionAlertConfiguration.objects.for_team(self.team.id).count() == 0
        for key in ("replay-vision-alerts",):
            flag = FeatureFlag.objects.get(team=self.team, key=key)
            assert flag.filters["groups"][0]["properties"][0]["value"] == []
