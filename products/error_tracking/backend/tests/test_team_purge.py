from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.team import Team
from posthog.models.team.util import TeamPurgeStopped, _delete_misc_small_tables_for_teams, delete_team_records

from products.error_tracking.backend.logic.team_purge import delete_stack_frames_and_symbol_sets_for_team
from products.error_tracking.backend.models import ErrorTrackingStackFrame, ErrorTrackingSymbolSet


@patch("products.error_tracking.backend.logic.team_purge.time.sleep")
class TestDeleteStackFramesAndSymbolSetsForTeam(BaseTest):
    def _create_frames_and_symbol_sets(self, team: Team) -> None:
        symbol_sets = [ErrorTrackingSymbolSet.objects.create(team=team, ref=f"ref_{i}") for i in range(3)]
        # Three parts share a raw id, so small batches end inside a run of equal raw ids.
        frames = [("raw_a", 0), ("raw_a", 1), ("raw_a", 2), ("raw_b", 0), ("raw_c", 0)]
        ErrorTrackingStackFrame.objects.bulk_create(
            ErrorTrackingStackFrame(
                team=team, raw_id=raw_id, part=part, symbol_set=symbol_sets[part], contents={}, resolved=True
            )
            for raw_id, part in frames
        )

    @parameterized.expand([(1,), (2,), (10000,)])
    def test_deletes_every_frame_and_symbol_set_of_the_team_and_no_other(
        self, _sleep: MagicMock, batch_size: int
    ) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._create_frames_and_symbol_sets(self.team)
        self._create_frames_and_symbol_sets(other_team)

        assert delete_stack_frames_and_symbol_sets_for_team(self.team.id, batch_size=batch_size)

        assert not ErrorTrackingStackFrame.objects.filter(team_id=self.team.id).exists()
        assert not ErrorTrackingSymbolSet.objects.filter(team_id=self.team.id).exists()
        assert ErrorTrackingStackFrame.objects.filter(team_id=other_team.id).count() == 5
        assert ErrorTrackingSymbolSet.objects.filter(team_id=other_team.id).count() == 3

    def test_stop_ends_the_purge_between_batches(self, _sleep: MagicMock) -> None:
        self._create_frames_and_symbol_sets(self.team)
        stops = iter([False, True])

        assert not delete_stack_frames_and_symbol_sets_for_team(
            self.team.id, should_stop=lambda: next(stops), batch_size=2
        )

        assert ErrorTrackingStackFrame.objects.filter(team_id=self.team.id).count() == 3
        assert ErrorTrackingSymbolSet.objects.filter(team_id=self.team.id).count() == 3

    def test_team_deletion_small_tables_step_runs_the_purge(self, _sleep: MagicMock) -> None:
        self._create_frames_and_symbol_sets(self.team)

        _delete_misc_small_tables_for_teams([self.team.id])

        assert not ErrorTrackingStackFrame.objects.filter(team_id=self.team.id).exists()
        assert not ErrorTrackingSymbolSet.objects.filter(team_id=self.team.id).exists()

    def test_team_records_step_runs_the_purge_before_the_cascade(self, _sleep: MagicMock) -> None:
        self._create_frames_and_symbol_sets(self.team)

        with self.assertRaisesRegex(TeamPurgeStopped, "stack frame purge"):
            delete_team_records([self.team.id], should_stop=lambda: True)

        assert Team.objects.filter(id=self.team.id).exists()
        assert ErrorTrackingStackFrame.objects.filter(team_id=self.team.id).count() == 5
