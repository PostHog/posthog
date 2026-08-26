from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.session_recording_links import (
    ReplayGateRewrite,
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
    # Both ways of asking "does a team gate replay on this flag" have to give the same answer.
    # `teams_gating_replay_on_flag` asks Postgres with JSONB containment, one flag at a time, and
    # backs the relink and the delete guard's unannotated fallback. `replay_gated_flags` scans a
    # project's stored config in Python and backs the bulk guard and the list annotation. A
    # disagreement lets a flag delete through one path that the other refuses, and the team stops
    # recording with nothing raised anywhere.

    # Each case stores a gate built from the flag under test and an unrelated flag, so a matcher
    # that ignores which flag a reference names fails rather than passing by coincidence.
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
            # The stored key has moved on, but the id still names the flag. Only the guards keep a
            # delete from taking away the repair command's one route back.
            (
                "trigger_group_stale_key_live_id",
                lambda gate, other: (None, [{"flag": {"id": gate.id, "key": "stale"}}]),
                GATED,
            ),
            # Nothing type-checks `conditions.flag`'s id on write, and Postgres compares JSON
            # numbers numerically, so a stored float satisfies the containment probe. The Python
            # scan has to read it the same way or the two matchers split.
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
        # Keys are unique only within a project, so an unscoped matcher would call a flag gated
        # because an unrelated project happens to store the same key.
        gate_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate")
        other_project_team = Team.objects.create(organization=self.organization)
        other_project_team.session_recording_trigger_groups = trigger_groups({"flag": "replay-gate"})
        other_project_team.save()

        assert teams_gating_replay_on_flag(gate_flag, key=gate_flag.key).exists() is False
        assert replay_gated_flags(self.team.project_id).gates(gate_flag) is False


class TestReplayGateWritesUseTheLockedRow(BaseTest):
    # Both rewrites replace a whole column, and callers select their teams in one batch before
    # looping, so a write built from the copy the caller selected would put back an admin edit that
    # landed in between and republish it to the SDKs. These pin that the rewrite is computed from
    # the row as it exists at write time.

    def test_an_edit_to_the_linked_flag_since_the_caller_looked_survives(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-new")
        set_linked_flag(self.team, {"id": flag.id, "key": "gate-old", "variant": "control"})

        # An admin switches the variant after the caller picked this team out of its batch.
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

        # An admin repoints the gate at another flag, which this rename has no business touching.
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
