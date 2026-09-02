import os
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

import requests
from parameterized import parameterized

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.replay_vision.backend.management.commands.migrate_vision_actions import (
    ALERTS_FLAG_KEY,
    SCOUTS_FLAG_KEY,
    _FlagsApiTargeting,
    rrule_to_cron,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import ActionMode, TriggerType, VisionAction
from products.replay_vision.backend.models.vision_alert import VisionAlertConfiguration, VisionAlertKind
from products.replay_vision.backend.scout_digest_body import compose_digest_scout_body

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
        assert str(self.scanner.id) in kwargs["body"]
        assert "Focus on payment failures." in kwargs["body"]
        assert "the verdict is one of `fail`" in kwargs["body"]
        assert "fall back to the last 7 days" in kwargs["body"]
        assert "Read at most" not in kwargs["body"]
        assert kwargs["config_options"]["run_cron_schedule"] == "0 9 * * 1"
        assert kwargs["config_options"]["output_destinations"]["slack"]["channel_id"] == "C123"
        action.refresh_from_db()
        assert action.enabled is False
        assert action.synthesis_config["migrated_to"] == kwargs["name"]

    def test_digest_without_prompt_guide_gets_the_plain_template(self) -> None:
        self._make_action(
            name="Plain digest",
            mode=ActionMode.GROUP_SUMMARY,
            is_scanner_digest=False,
            selection={},
            synthesis_config={},
        )
        with patch("products.signals.backend.facade.api.create_scout_for_source") as create_scout:
            self._run()
        body = create_scout.call_args.kwargs["body"]
        assert "What the digest's author asked for" not in body
        assert "This digest covers only part of what the scanner sees" not in body
        assert body == compose_digest_scout_body(str(self.scanner.id))

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

    def test_flag_mode_arguments_are_validated(self) -> None:
        with self.assertRaises(CommandError):
            call_command("migrate_vision_actions")
        with self.assertRaises(CommandError):
            call_command(
                "migrate_vision_actions",
                "--flag-team-id",
                "2",
                "--flags-api-host",
                "https://example.com",
                "--flags-api-project",
                "2",
            )
        with self.assertRaises(CommandError):
            call_command("migrate_vision_actions", "--flags-api-project", "2")
        with patch.dict(os.environ), self.assertRaises(CommandError):
            os.environ.pop("POSTHOG_FLAGS_API_KEY", None)
            call_command(
                "migrate_vision_actions", "--flags-api-host", "https://example.com", "--flags-api-project", "2"
            )
        with patch.dict(os.environ, {"POSTHOG_FLAGS_API_KEY": "phx_test"}), self.assertRaises(CommandError):
            call_command("migrate_vision_actions", "--flags-api-host", "http://example.com", "--flags-api-project", "2")

    def _api_session(self) -> MagicMock:
        flags = {
            ALERTS_FLAG_KEY: {
                "id": 5,
                "key": ALERTS_FLAG_KEY,
                "filters": {"groups": [{"properties": [{"key": "$group_key", "value": []}]}]},
            },
            SCOUTS_FLAG_KEY: {
                "id": 6,
                "key": SCOUTS_FLAG_KEY,
                "filters": {"groups": [{"properties": [{"key": "$group_key", "value": []}]}]},
            },
        }

        def get(url: str, params: dict | None = None, timeout: int | None = None) -> MagicMock:
            assert "/api/projects/2/feature_flags" in url
            response = MagicMock()
            if params is not None:
                response.json.return_value = {"results": [flags[params["key"]]]}
            else:
                flag_id = int(url.rstrip("/").rsplit("/", 1)[-1])
                response.json.return_value = next(f for f in flags.values() if f["id"] == flag_id)
            return response

        session = MagicMock()
        session.get.side_effect = get
        return session

    def test_flags_api_mode_widens_remote_flags(self) -> None:
        action = self._make_action(alert_config={"frequency": "every_match"}, selection={})
        session = self._api_session()
        with (
            patch(f"{_CMD}.requests.Session", return_value=session),
            patch(f"{_CMD}.Command._create_destinations"),
            patch.dict(os.environ, {"POSTHOG_FLAGS_API_KEY": "phx_test"}),
        ):
            call_command(
                "migrate_vision_actions",
                "--execute",
                "--flags-api-host",
                "https://example.com",
                "--flags-api-project",
                "2",
            )
        session.headers.__setitem__.assert_any_call("Authorization", "Bearer phx_test")
        assert session.patch.call_count == 2
        patched_urls = {call.args[0] for call in session.patch.call_args_list}
        assert patched_urls == {
            "https://example.com/api/projects/2/feature_flags/5/",
            "https://example.com/api/projects/2/feature_flags/6/",
        }
        for call in session.patch.call_args_list:
            values = call.kwargs["json"]["filters"]["groups"][0]["properties"][0]["value"]
            assert str(action.team.organization_id) in values

    def test_flags_api_dry_run_preflights_but_never_patches(self) -> None:
        self._make_action(alert_config={"frequency": "every_match"}, selection={})
        session = self._api_session()
        with (
            patch(f"{_CMD}.requests.Session", return_value=session),
            patch.dict(os.environ, {"POSTHOG_FLAGS_API_KEY": "phx_test"}),
        ):
            call_command(
                "migrate_vision_actions", "--flags-api-host", "https://example.com", "--flags-api-project", "2"
            )
        assert session.get.call_count == 2
        session.patch.assert_not_called()


class TestComposeDigestScoutBody(SimpleTestCase):
    def test_legacy_narrowing_shapes(self) -> None:
        capped = compose_digest_scout_body("sid", max_observations=25)
        assert "Read at most 25 matching observations" in capped
        assert "Read at most" not in compose_digest_scout_body("sid", max_observations=100)

        bare = compose_digest_scout_body("sid", selection={"verdict": "fail"})
        assert "the verdict is one of `fail`" in bare
        assert bare == compose_digest_scout_body("sid", selection={"verdict": ["fail"]})

        malformed = compose_digest_scout_body("sid", selection={"window_days": "7"}, prompt_guide=None)
        assert "fall back to the last 24 hours" in malformed


class TestFlagsApiTargeting(SimpleTestCase):
    def _client_with(self, flag: dict) -> tuple[_FlagsApiTargeting, MagicMock]:
        session = MagicMock()
        session.get.return_value.json.return_value = {"results": [flag], **flag}
        with patch(f"{_CMD}.requests.Session", return_value=session):
            client = _FlagsApiTargeting("https://example.com/", 2, "phx_test")
        client.preflight((flag["key"],))
        return client, session

    def test_preflight_rejects_missing_flag(self) -> None:
        session = MagicMock()
        session.get.return_value.json.return_value = {"results": []}
        with patch(f"{_CMD}.requests.Session", return_value=session):
            client = _FlagsApiTargeting("https://example.com", 2, "phx_test")
        with self.assertRaises(CommandError):
            client.preflight(("missing",))

    def test_add_group_is_idempotent_and_fails_closed(self) -> None:
        flag = {
            "id": 5,
            "key": "k",
            "filters": {"groups": [{"properties": [{"key": "$group_key", "value": ["org-a"]}]}]},
        }
        client, session = self._client_with(flag)
        assert client.add_group("k", "org-a") is None
        session.patch.assert_not_called()
        assert client.add_group("k", "org-b") is None
        session.patch.assert_called_once()

        unwidenable = {"id": 6, "key": "k", "filters": {"groups": []}}
        client2, _ = self._client_with(unwidenable)
        assert client2.add_group("k", "org-a") == "no organization targeting to widen"

    def test_request_failure_fails_closed(self) -> None:
        flag = {"id": 5, "key": "k", "filters": {"groups": [{"properties": [{"key": "$group_key", "value": []}]}]}}
        client, session = self._client_with(flag)
        session.patch.side_effect = requests.ConnectionError("boom")
        problem = client.add_group("k", "org-a")
        assert problem is not None and "API request failed" in problem
        session.patch.side_effect = None
        session.patch.return_value = MagicMock()
        assert client.add_group("k", "org-b") is None
