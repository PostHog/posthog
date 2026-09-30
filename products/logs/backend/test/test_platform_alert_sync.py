from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import backfill_platform_alert_configurations

PLATFORM_NEXT_CHECK = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
LEGACY_NEXT_CHECK = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)


class TestPlatformAlertSync(BaseTest):
    def _legacy_alert(self, name: str = "API errors") -> LogsAlertConfiguration:
        return LogsAlertConfiguration.objects.create(
            team=self.team, name=name, filters={"severityLevels": ["error"]}, threshold_count=10
        )

    def _copies(self) -> list[PlatformAlertConfiguration]:
        return list(PlatformAlertConfiguration.objects.for_team(self.team.id).all())

    def _backfilled(self) -> tuple[LogsAlertConfiguration, PlatformAlertConfiguration]:
        legacy = self._legacy_alert()
        backfill_platform_alert_configurations(team_id=self.team.id)
        (copy,) = self._copies()
        copy.next_check_at = PLATFORM_NEXT_CHECK
        copy.save(update_fields=["next_check_at"])
        return legacy, copy

    def test_an_edit_reaches_the_copy_and_leaves_its_schedule_alone(self) -> None:
        legacy, copy = self._backfilled()
        snooze_until = datetime(2026, 10, 1, tzinfo=UTC)

        legacy.threshold_count = 500
        legacy.filters = {"severityLevels": ["fatal"]}
        legacy.snooze_until = snooze_until
        legacy.next_check_at = LEGACY_NEXT_CHECK
        legacy.save()

        copy.refresh_from_db()
        assert (copy.threshold_count, copy.source_config, copy.next_check_at) == (
            500,
            {"severityLevels": ["fatal"]},
            PLATFORM_NEXT_CHECK,
        )
        assert [a.snooze_until for a in PlatformAlert.objects.for_team(self.team.id).filter(configuration=copy)] == [
            snooze_until
        ]

    def test_an_alert_that_was_never_backfilled_gets_no_copy(self) -> None:
        legacy = self._legacy_alert()
        legacy.threshold_count = 500
        legacy.save()

        assert self._copies() == []

    def test_a_runtime_only_save_does_not_touch_the_copy(self) -> None:
        legacy, copy = self._backfilled()

        legacy.name = "Renamed in memory only"
        legacy.state = LogsAlertConfiguration.State.FIRING
        legacy.save(update_fields=["state", "updated_at"])

        copy.refresh_from_db()
        assert copy.name == "API errors"

    def test_deleting_the_alert_deletes_its_copy(self) -> None:
        legacy, _ = self._backfilled()

        legacy.delete()

        assert self._copies() == []

    def test_the_kill_switch_stops_edits_and_deletes_reaching_the_copy(self) -> None:
        legacy, copy = self._backfilled()

        with patch("products.logs.backend.platform_alert_sync.SYNC_ENABLED", False):
            legacy.threshold_count = 500
            legacy.save()
            copy.refresh_from_db()
            assert copy.threshold_count == 10

            legacy.delete()
            assert self._copies() == [copy]

    def test_a_failed_sync_does_not_block_the_edit(self) -> None:
        legacy, _ = self._backfilled()

        with patch(
            "products.logs.backend.platform_alert_sync.sync_existing_configuration",
            side_effect=RuntimeError("platform unavailable"),
        ):
            legacy.threshold_count = 500
            legacy.save()

        legacy.refresh_from_db()
        assert legacy.threshold_count == 500
