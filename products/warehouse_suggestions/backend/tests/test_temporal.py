from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client.execute import KillSwitchLevel
from posthog.models.team import Team

from products.warehouse_suggestions.backend.temporal.activities import team_batches
from products.warehouse_suggestions.backend.temporal.contracts import WarehouseSuggestionsInputs

ACTIVITIES = "products.warehouse_suggestions.backend.temporal.activities"


class TestTeamBatches(BaseTest):
    @parameterized.expand(
        [
            ("kill_switch_off", KillSwitchLevel.OFF, True),
            ("kill_switch_on", KillSwitchLevel.LIGHT, False),
        ]
    )
    def test_picks_flagged_teams_skips_demo_teams_and_stops_under_the_kill_switch(
        self, _name: str, kill_switch: KillSwitchLevel, expect_team: bool
    ) -> None:
        demo_team = Team.objects.create(organization=self.organization, is_demo=True)
        unflagged_team = Team.objects.create(organization=self.organization)
        flagged = {self.team.pk, demo_team.pk}

        with (
            patch(f"{ACTIVITIES}.get_kill_switch_level", return_value=kill_switch),
            patch(f"{ACTIVITIES}.is_warehouse_suggestions_enabled", side_effect=lambda team: team.pk in flagged),
        ):
            batches = team_batches(WarehouseSuggestionsInputs(team_ids=[self.team.pk, demo_team.pk, unflagged_team.pk]))

        assert batches == ([[self.team.pk]] if expect_team else [])
