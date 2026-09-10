from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.session_recording_links import (
    ReplayGateRewrite,
    relink_teams,
    replay_gated_flags,
    rewritten_linked_flag,
    rewritten_trigger_groups,
    save_replay_gate_rewrites,
    teams_gating_replay_on_flag,
    trigger_group_flag_refs,
)
from products.feature_flags.backend.test.replay_gate_fixtures import set_linked_flag, set_trigger_groups, trigger_groups

GATED = True
NOT_GATED = False


class TestReplayGateMatchersAgree(BaseTest):
    @parameterized.expand(
        [
            ("linked_flag_by_id", lambda gate, other: ({"id": gate.id, "key": "stale"}, None), GATED),
            (
                "linked_flag_naming_another_flag",
                lambda gate, other: ({"id": other.id, "key": gate.key}, None),
                NOT_GATED,
            ),
            ("trigger_group_bare_key", lambda gate, other: (None, [{"flag": gate.key}]), GATED),
            (
                "trigger_group_object_key",
                lambda gate, other: (None, [{"flag": {"id": gate.id, "key": gate.key}}]),
                GATED,
            ),
            ("trigger_group_object_without_id", lambda gate, other: (None, [{"flag": {"key": gate.key}}]), GATED),
            (
                "trigger_group_stale_key_live_id",
                lambda gate, other: (None, [{"flag": {"id": gate.id, "key": "stale"}}]),
                GATED,
            ),
            (
                "trigger_group_float_id",
                lambda gate, other: (None, [{"flag": {"id": float(gate.id), "key": "stale"}}]),
                GATED,
            ),
            ("trigger_group_naming_another_flag", lambda gate, other: (None, [{"flag": other.key}]), NOT_GATED),
            ("trigger_group_key_prefix", lambda gate, other: (None, [{"flag": f"{gate.key}-v2"}]), NOT_GATED),
            ("trigger_group_key_only_in_events", lambda gate, other: (None, [{"events": [gate.key]}]), NOT_GATED),
            (
                "trigger_group_without_a_flag",
                lambda gate, other: (None, [{"urls": [{"url": "/x", "matching": "regex"}]}]),
                NOT_GATED,
            ),
            ("second_group_matches", lambda gate, other: (None, [{"flag": other.key}, {"flag": gate.key}]), GATED),
            ("nothing_stored", lambda gate, other: (None, None), NOT_GATED),
            ("empty_groups", lambda gate, other: (None, []), NOT_GATED),
        ]
    )
    def test_both_matchers_agree(self, _name: str, build_gate: Any, expected: bool) -> None:
        gate_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate")
        other_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="unrelated")
        linked_flag, group_conditions = build_gate(gate_flag, other_flag)

        self.team.session_recording_linked_flag = linked_flag
        self.team.session_recording_trigger_groups = (
            None if group_conditions is None else trigger_groups(*group_conditions)
        )
        self.team.save()

        assert teams_gating_replay_on_flag(gate_flag, key=gate_flag.key).exists() is expected
        assert replay_gated_flags(self.team.project_id).gates(gate_flag) is expected

    def test_both_matchers_ignore_another_project(self) -> None:
        gate_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate")
        other_project_team = Team.objects.create(organization=self.organization)
        other_project_team.session_recording_trigger_groups = trigger_groups({"flag": "replay-gate"})
        other_project_team.save()

        assert teams_gating_replay_on_flag(gate_flag, key=gate_flag.key).exists() is False
        assert replay_gated_flags(self.team.project_id).gates(gate_flag) is False


class TestReplayGateWritesUseTheLockedRow(BaseTest):
    def test_an_edit_to_the_linked_flag_since_the_caller_looked_survives(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-new")
        set_linked_flag(self.team, {"id": flag.id, "key": "gate-old", "variant": "control"})

        set_linked_flag(Team.objects.get(pk=self.team.pk), {"id": flag.id, "key": "gate-old", "variant": "test"})

        save_replay_gate_rewrites(
            self.team.pk,
            lambda team: ReplayGateRewrite(
                linked_flag=rewritten_linked_flag(
                    team.session_recording_linked_flag, flag_id=flag.id, new_key="gate-new"
                )
            ),
        )

        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": flag.id, "key": "gate-new", "variant": "test"}

    def test_skips_the_write_when_the_team_now_gates_on_a_different_flag(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-new")
        other_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="other-gate")
        set_linked_flag(self.team, {"id": flag.id, "key": "gate-old"})

        set_linked_flag(Team.objects.get(pk=self.team.pk), {"id": other_flag.id, "key": "other-gate"})

        save_replay_gate_rewrites(
            self.team.pk,
            lambda team: ReplayGateRewrite(
                linked_flag=rewritten_linked_flag(
                    team.session_recording_linked_flag, flag_id=flag.id, new_key="gate-new"
                )
            ),
        )

        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": other_flag.id, "key": "other-gate"}

    def test_a_group_added_since_the_caller_looked_survives_and_the_rename_moves_its_own_group(self) -> None:
        set_trigger_groups(self.team, {"flag": "gate-old"})

        # Prepending shifts the reference the rename is about off index 0, so a rewrite keyed by
        # indices read earlier would move the wrong group.
        admin = Team.objects.get(pk=self.team.pk)
        stored = admin.session_recording_trigger_groups
        stored["groups"].insert(
            0, {"id": "added", "sampleRate": 0.5, "conditions": {"matchType": "any", "events": ["signup"]}}
        )
        admin.session_recording_trigger_groups = stored
        admin.save()

        def rewrite(team: Team) -> ReplayGateRewrite:
            groups = team.session_recording_trigger_groups
            moving = {ref.group_index: "gate-new" for ref in trigger_group_flag_refs(groups) if ref.key == "gate-old"}
            return ReplayGateRewrite(trigger_groups=rewritten_trigger_groups(groups, moving))

        save_replay_gate_rewrites(self.team.pk, rewrite)

        self.team.refresh_from_db()
        groups = self.team.session_recording_trigger_groups["groups"]
        assert [group["id"] for group in groups] == ["added", "group-0"]
        assert groups[0]["conditions"] == {"matchType": "any", "events": ["signup"]}
        assert groups[1]["conditions"]["flag"] == "gate-new"


class TestRelinkTeamsConvergesOnTheStoredKey(BaseTest):
    def test_a_stale_callback_does_not_put_back_the_key_it_captured(self) -> None:
        # Renames serialize on the flag row. Their post-commit callbacks do not, so the callback
        # for gate-a to gate-b can run after gate-b to gate-c has committed and relinked. Taking
        # the key from the signal's own instance would move both columns back to gate-b, which no
        # flag holds, and the SDKs stop recording on a key they cannot resolve.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-c")
        set_linked_flag(self.team, {"id": flag.id, "key": "gate-a"})
        set_trigger_groups(self.team, {"flag": "gate-a"})

        stale = FeatureFlag(pk=flag.pk, team=flag.team, key="gate-b")
        relink_teams(stale, old_key="gate-a")

        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": flag.id, "key": "gate-c"}
        assert self.team.session_recording_trigger_groups["groups"][0]["conditions"]["flag"] == "gate-c"


class TestRelinkTeamsIsolatesAWriteFailure(BaseTest):
    def test_one_teams_write_failure_does_not_strand_its_siblings(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-old")
        other_team = Team.objects.create(organization=self.organization, project=self.team.project)
        set_linked_flag(self.team, {"id": flag.id, "key": "gate-old"})
        set_linked_flag(other_team, {"id": flag.id, "key": "gate-old"})

        real_save = save_replay_gate_rewrites
        failed_for: list[int] = []

        # Fails whichever team comes up first, so the assertions hold whatever order the scan
        # returns them in.
        def fail_on_the_first_team(team_id: int, compute: Any) -> None:
            if not failed_for:
                failed_for.append(team_id)
                raise Exception("simulated write failure")
            real_save(team_id, compute)

        flag.key = "gate-new"
        with patch(
            "products.feature_flags.backend.session_recording_links.save_replay_gate_rewrites",
            side_effect=fail_on_the_first_team,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                flag.save()

        assert len(failed_for) == 1
        stored = {
            team.pk: team.session_recording_linked_flag
            for team in Team.objects.filter(pk__in=[self.team.pk, other_team.pk])
        }
        stranded = failed_for[0]
        relinked = ({self.team.pk, other_team.pk} - {stranded}).pop()
        assert stored[stranded] == {"id": flag.id, "key": "gate-old"}
        assert stored[relinked] == {"id": flag.id, "key": "gate-new"}


class TestRelinkTeamsAbsorbsALookupFailure(BaseTest):
    def test_a_failed_team_lookup_does_not_fail_the_committed_rename(self) -> None:
        # The relink runs after the rename has committed, and its own reads sit outside the
        # per-team handler. A fault in them would reach the caller, so a rename that already
        # landed would answer with an error the caller cannot act on.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-old")
        set_linked_flag(self.team, {"id": flag.id, "key": "gate-old"})

        flag.key = "gate-new"
        with patch(
            "products.feature_flags.backend.session_recording_links.teams_gating_replay_on_flag",
            side_effect=Exception("simulated lookup failure"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                flag.save()

        assert FeatureFlag.objects.get(pk=flag.pk).key == "gate-new"
        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": flag.id, "key": "gate-old"}
