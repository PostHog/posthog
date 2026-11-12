from datetime import UTC, datetime
from io import StringIO
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.models import Team, User
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade.api import list_configurations
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import (
    backfill_platform_alert_configurations,
    disable_platform_alert_configurations,
)


class TestPlatformLogsAlertBackfill(APIBaseTest):
    def _alert(
        self, team: Team, name: str = "API errors", created_by: User | None = None, **fields: Any
    ) -> LogsAlertConfiguration:
        return LogsAlertConfiguration.objects.create(
            team=team, name=name, filters={"serviceNames": ["api"]}, created_by=created_by, **fields
        )

    def _copies(self, team: Team) -> dict[UUID | None, Any]:
        with team_scope(team.id):
            page = list_configurations(team_id=team.id, source_kinds=[SourceKind.LOGS.value], limit=10, offset=0)
        return {view.legacy_configuration_id: view for view in page.configurations}

    def test_a_sample_copies_whole_teams_and_widening_it_only_adds_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        low, high = sorted([self.team, other_team], key=lambda team: team.id % 100)
        low_alerts = {self._alert(low).id, self._alert(low, name="Slow requests").id}
        high_alert = self._alert(high).id

        backfill_platform_alert_configurations(sample_percent=low.id % 100 + 1)
        assert (set(self._copies(low)), set(self._copies(high))) == (low_alerts, set())

        backfill_platform_alert_configurations(sample_percent=high.id % 100 + 1)
        assert (set(self._copies(low)), set(self._copies(high))) == (low_alerts, {high_alert})

    def test_one_alert_the_copy_rejects_does_not_stop_the_rest(self) -> None:
        self._alert(self.team)
        self._alert(self.team, name="Slow requests")

        with patch(
            "products.logs.backend.platform_alert_backfill.upsert_configuration",
            side_effect=[RuntimeError("rejected"), True],
        ):
            counts = backfill_platform_alert_configurations(team_id=self.team.id)

        assert (counts.created, counts.failed) == (1, 1)

    def test_disabling_stops_every_copy_and_a_rerun_turns_them_back_on(self) -> None:
        self._alert(self.team)
        self._alert(self.team, name="Slow requests")
        backfill_platform_alert_configurations(team_id=self.team.id)

        assert disable_platform_alert_configurations(team_id=self.team.id) == 2
        assert {view.enabled for view in self._copies(self.team).values()} == {False}

        backfill_platform_alert_configurations(team_id=self.team.id)
        assert {view.enabled for view in self._copies(self.team).values()} == {True}

    def test_named_alerts_are_the_only_ones_copied_and_the_only_ones_switched_off(self) -> None:
        kept, rotated = self._alert(self.team).id, self._alert(self.team, name="Slow requests").id
        self._alert(self.team, name="Not named")

        backfill_platform_alert_configurations(alert_ids=[kept, rotated])
        assert set(self._copies(self.team)) == {kept, rotated}

        assert disable_platform_alert_configurations(alert_ids=[rotated]) == 1
        assert {key: view.enabled for key, view in self._copies(self.team).items()} == {kept: True, rotated: False}

    def test_copies_carry_the_creator_and_the_command_fills_only_copies_without_one(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@example.com", None)
        copied = self._alert(self.team, created_by=self.user)
        predates_column = self._alert(self.team, name="Slow requests")
        no_creator = self._alert(self.team, name="Not named")
        backfill_platform_alert_configurations(team_id=self.team.id)
        LogsAlertConfiguration.objects.filter(id=predates_column.id).update(created_by=self.user)
        LogsAlertConfiguration.objects.filter(id=copied.id).update(created_by=other_user)

        dry_run = StringIO()
        call_command("backfill_platform_logs_alert_creators", dry_run=True, stdout=dry_run)
        assert self._copies(self.team)[predates_column.id].created_by_id is None
        call_command("backfill_platform_logs_alert_creators", stdout=StringIO())

        assert "Would fill the creator on 1 " in dry_run.getvalue()
        assert {key: view.created_by_id for key, view in self._copies(self.team).items()} == {
            copied.id: self.user.id,
            predates_column.id: self.user.id,
            no_creator.id: None,
        }

    def test_copies_carry_first_enabled_at_and_the_command_matches_only_copies_that_differ(self) -> None:
        first, later = datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC)
        other_team = Team.objects.create(organization=self.organization, name="other")
        copied = self._alert(self.team, first_enabled_at=first)
        stale = self._alert(self.team, name="Slow requests", first_enabled_at=first)
        draft = self._alert(self.team, name="Draft", enabled=False)
        elsewhere = self._alert(other_team, first_enabled_at=first)
        backfill_platform_alert_configurations()
        assert self._copies(self.team)[copied.id].first_enabled_at == first
        LogsAlertConfiguration.objects.filter(id__in=[stale.id, elsewhere.id]).update(first_enabled_at=later)

        dry_run = StringIO()
        call_command("backfill_platform_logs_alert_first_enabled_at", team_ids=[self.team.id], stdout=dry_run)
        assert self._copies(self.team)[stale.id].first_enabled_at == first
        call_command(
            "backfill_platform_logs_alert_first_enabled_at", team_ids=[self.team.id], apply=True, stdout=StringIO()
        )
        rerun = StringIO()
        call_command("backfill_platform_logs_alert_first_enabled_at", team_ids=[self.team.id], apply=True, stdout=rerun)

        assert "Would set first_enabled_at on 1 " in dry_run.getvalue()
        assert "Set first_enabled_at on 0 " in rerun.getvalue()
        assert {key: view.first_enabled_at for key, view in self._copies(self.team).items()} == {
            copied.id: first,
            stale.id: later,
            draft.id: None,
        }
        assert self._copies(other_team)[elsewhere.id].first_enabled_at == first
