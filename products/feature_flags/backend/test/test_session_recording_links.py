from posthog.test.base import BaseTest

from posthog.models import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.session_recording_links import update_linked_flag_key


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
