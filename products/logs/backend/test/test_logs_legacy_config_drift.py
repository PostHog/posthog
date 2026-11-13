from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any

from posthog.test.base import APIBaseTest

from django.core.management import CommandError, call_command
from django.utils import timezone

from parameterized import parameterized

from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_cutover import cut_over_team

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


class TestLogsLegacyConfigDrift(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.alert = LogsAlertConfiguration.objects.create(
            team=self.team,
            name="Errors",
            filters={"severityLevels": ["error"], "serviceNames": ["api"]},
            next_check_at=NOW + timedelta(minutes=3),
        )
        (result,) = cut_over_team(self.team.id, now=NOW)
        assert result.skipped is None

    def _report(self, **options: Any) -> tuple[str, CommandError | None]:
        out = StringIO()
        try:
            call_command("report_legacy_config_drift", source=["logs"], team_id=self.team.id, stdout=out, **options)
        except CommandError as error:
            return out.getvalue(), error
        return out.getvalue(), None

    def test_a_copy_that_matches_its_row_reports_no_drift(self) -> None:
        output, error = self._report()

        assert error is None
        assert "Compared 1 platform-owned alerts across logs: 0 differ" in output

    @parameterized.expand(
        [
            ("name", {"name": "renamed"}, ["name"]),
            ("enabled", {"enabled": False}, ["enabled"]),
            ("cadence", {"check_interval_minutes": 30}, ["check_interval_minutes"]),
            ("snooze", {"snooze_until": timezone.now() + timedelta(days=1)}, ["snooze_until"]),
            ("evaluation_periods", {"evaluation_periods": 3}, ["evaluation_periods"]),
            ("threshold", {"threshold_count": 7}, ["source_config.condition.threshold_count"]),
            ("operator", {"threshold_operator": "below"}, ["source_config.condition.threshold_operator"]),
            ("filters", {"filters": {"severityLevels": ["error"]}}, ["source_config.filters.serviceNames"]),
            ("first_enabled_at", {"first_enabled_at": NOW}, ["first_enabled_at"]),
        ]
    )
    def test_an_edit_the_copy_missed_is_reported_per_setting(
        self, _name: str, row_change: dict[str, Any], settings: list[str]
    ) -> None:
        LogsAlertConfiguration.objects.filter(id=self.alert.id).update(**row_change)

        output, error = self._report()

        assert error is not None and error.returncode == 1
        for setting in settings:
            assert f"team={self.team.id} source=logs setting={setting} alerts=1 sample=[{self.alert.id}]" in output
        assert output.count("setting=") == len(settings)

    def test_drift_is_counted_across_batches_and_a_missing_copy_is_reported(self) -> None:
        second = LogsAlertConfiguration.objects.create(
            team=self.team,
            name="Warnings",
            filters={"severityLevels": ["warn"]},
            next_check_at=NOW + timedelta(minutes=3),
        )
        cut_over_team(self.team.id, now=NOW)
        LogsAlertConfiguration.objects.filter(team=self.team).update(name="renamed")
        LogsAlertConfiguration.objects.create(
            team=self.team, name="Uncopied", filters={}, owner=PlatformAlertOwner.PLATFORM
        )

        output, error = self._report(batch_size=1, sample_size=1)

        assert error is not None
        assert f"setting=name alerts=2 sample=[{min(self.alert.id, second.id)}]" in output
        assert "setting=copy_missing alerts=1" in output
        assert "Compared 3 platform-owned alerts across logs: 3 differ" in output
