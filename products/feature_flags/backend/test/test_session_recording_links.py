from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.session_recording_links import relink_teams, update_linked_flag_key


class TestUpdateLinkedFlagKey(BaseTest):
    def test_preserves_a_concurrent_edit_to_the_linked_flag(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate")
        self.team.session_recording_linked_flag = {"id": flag.id, "key": "replay-gate", "variant": "control"}
        self.team.save()
        # Stands in for a team a caller loaded earlier in a batch, before the edit below lands.
        stale_team = Team.objects.get(pk=self.team.pk)

        self.team.session_recording_linked_flag = {"id": flag.id, "key": "replay-gate", "variant": "test"}
        self.team.save()

        update_linked_flag_key(stale_team, flag.id, "replay-gate-v2")

        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {
            "id": flag.id,
            "key": "replay-gate-v2",
            "variant": "test",
        }

    def test_skips_the_write_when_the_team_now_links_a_different_flag(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate")
        other_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="other-gate")
        self.team.session_recording_linked_flag = {"id": flag.id, "key": "replay-gate"}
        self.team.save()
        stale_team = Team.objects.get(pk=self.team.pk)

        # Concurrent edit: an admin repoints the team at a different flag entirely.
        self.team.session_recording_linked_flag = {"id": other_flag.id, "key": "other-gate"}
        self.team.save()

        update_linked_flag_key(stale_team, flag.id, "replay-gate-v2")

        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": other_flag.id, "key": "other-gate"}


class TestRelinkTeams(BaseTest):
    def test_converges_on_the_current_key_despite_a_stale_signal_snapshot(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-c")
        # Stands in for an on_commit callback's captured snapshot from an earlier rename that
        # committed first but is only now getting around to relinking teams: the DB has already
        # moved on to a newer key by the time this callback runs.
        stale_flag = FeatureFlag(pk=flag.pk, team=flag.team, key="gate-b")
        # A faster, later rename's callback already brought this team up to date.
        self.team.session_recording_linked_flag = {"id": flag.id, "key": "gate-c"}
        self.team.save()

        relink_teams(stale_flag)

        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": flag.id, "key": "gate-c"}

    def test_one_teams_write_failure_does_not_strand_its_siblings(self) -> None:
        # relink_teams wraps each team's update in its own try/except so that one row it can't
        # write (a lock timeout, a constraint violation) doesn't stop the rename from reaching
        # every other team gating replay on the same flag.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-old")
        other_team = Team.objects.create(organization=self.organization, project=self.team.project)
        self.team.session_recording_linked_flag = {"id": flag.id, "key": "gate-old"}
        self.team.save()
        other_team.session_recording_linked_flag = {"id": flag.id, "key": "gate-old"}
        other_team.save()

        real_update_linked_flag_key = update_linked_flag_key

        def _raise_for_other_team(team: Team, expected_flag_id: int, new_key: str) -> None:
            if team.pk == other_team.pk:
                raise Exception("simulated write failure")
            real_update_linked_flag_key(team, expected_flag_id, new_key)

        flag.key = "gate-new"
        with patch(
            "products.feature_flags.backend.session_recording_links.update_linked_flag_key",
            side_effect=_raise_for_other_team,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                flag.save()

        self.team.refresh_from_db()
        other_team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": flag.id, "key": "gate-new"}
        assert other_team.session_recording_linked_flag == {"id": flag.id, "key": "gate-old"}
