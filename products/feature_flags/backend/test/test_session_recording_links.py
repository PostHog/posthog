from typing import Any

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.session_recording_links import replay_gated_flags, teams_gating_replay_on_flag
from products.feature_flags.backend.test.replay_gate_fixtures import trigger_groups

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
