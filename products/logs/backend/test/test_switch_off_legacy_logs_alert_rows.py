from io import StringIO
from uuid import UUID

from posthog.test.base import APIBaseTest

from django.core.management import CommandError, call_command

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import list_configurations, upsert_configuration
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.platform_alert_backfill import platform_upsert_of


class TestSwitchOffLegacyLogsAlertRows(APIBaseTest):
    def _alert(self, *, row_owner: PlatformAlertOwner, copy_owner: PlatformAlertOwner | None) -> LogsAlertConfiguration:
        alert = LogsAlertConfiguration.objects.create(
            team=self.team, name="API errors", filters={"serviceNames": ["api"]}, owner=row_owner
        )
        if copy_owner is not None:
            with team_scope(self.team.id):
                upsert_configuration(platform_upsert_of(alert))
                platform_testing.set_owner(platform_testing.copy_of(alert.id).id, copy_owner)
        return alert

    def _run(self, *options: str) -> str:
        out = StringIO()
        call_command("switch_off_legacy_logs_alert_rows", "--team-id", str(self.team.id), *options, stdout=out)
        return out.getvalue()

    def _enabled(self) -> tuple[dict[UUID, bool], dict[UUID | None, bool]]:
        rows = dict(LogsAlertConfiguration.objects.filter(team_id=self.team.id).values_list("id", "enabled"))
        with team_scope(self.team.id):
            page = list_configurations(team_id=self.team.id, source_kinds=[SourceKind.LOGS.value], limit=20, offset=0)
        return rows, {view.legacy_configuration_id: view.enabled for view in page.configurations}

    def test_switches_off_only_the_rows_of_alerts_the_platform_owns(self) -> None:
        moved = [
            self._alert(row_owner=PlatformAlertOwner.PLATFORM, copy_owner=PlatformAlertOwner.PLATFORM).id
            for _ in range(3)
        ]
        kept = {
            self._alert(row_owner=PlatformAlertOwner.SOURCE, copy_owner=PlatformAlertOwner.SOURCE).id,
            self._alert(row_owner=PlatformAlertOwner.SOURCE, copy_owner=None).id,
            self._alert(row_owner=PlatformAlertOwner.SOURCE, copy_owner=PlatformAlertOwner.PLATFORM).id,
        }
        rows_before, copies_before = self._enabled()
        updated_at_before = dict(LogsAlertConfiguration.objects.values_list("id", "updated_at"))
        activity_before = ActivityLog.objects.filter(team_id=self.team.id).count()

        assert self._run().splitlines()[-1] == "logs: 1 teams, 4 platform-owned alerts, 3 rows to switch off (dry run)"
        assert self._enabled() == (rows_before, copies_before)

        assert self._run("--apply", "--batch-size", "2").splitlines()[-1] == (
            "logs: 1 teams, 4 platform-owned alerts, 3 rows switched off"
        )
        rows, copies = self._enabled()
        assert {alert_id for alert_id, enabled in rows.items() if not enabled} == set(moved)
        assert all(rows[alert_id] for alert_id in kept)
        assert copies == copies_before
        assert ActivityLog.objects.filter(team_id=self.team.id).count() == activity_before
        assert not LogsAlertEvent.objects.filter(alert__team_id=self.team.id).exists()
        assert dict(LogsAlertConfiguration.objects.values_list("id", "updated_at")) == updated_at_before

        assert self._run("--apply").splitlines()[-1] == "logs: 1 teams, 4 platform-owned alerts, 0 rows switched off"

    def test_a_batch_size_below_one_is_refused(self) -> None:
        with self.assertRaises(CommandError):
            self._run("--apply", "--batch-size", "-1")
