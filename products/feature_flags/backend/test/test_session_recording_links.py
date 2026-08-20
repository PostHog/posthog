from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.session_recording_links import (
    jsonb_number_counts_as_flag_id,
    relink_teams,
    update_linked_flag_key,
)


class TestJsonbNumberCountsAsFlagId:
    @parameterized.expand(
        [
            ("int", 5, {5}, True),
            ("float_matching", 5.0, {5}, True),
            ("numeric_string", "5", {5}, False),
            ("string", "abc", {5}, False),
            ("none", None, {5}, False),
            ("different_number", 6, {5}, False),
            ("bool_true", True, {1}, False),
            ("bool_false", False, {0}, False),
        ]
    )
    def test_membership_semantics(self, _name: str, stored: Any, flag_ids: set[int], expected: bool) -> None:
        assert jsonb_number_counts_as_flag_id(stored, flag_ids) is expected


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
