from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade.api import list_configurations
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import (
    backfill_platform_alert_configurations,
    disable_platform_alert_configurations,
)


class TestPlatformLogsAlertBackfill(APIBaseTest):
    def _alert(self, team: Team, name: str = "API errors") -> LogsAlertConfiguration:
        return LogsAlertConfiguration.objects.create(team=team, name=name, filters={"serviceNames": ["api"]})

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
