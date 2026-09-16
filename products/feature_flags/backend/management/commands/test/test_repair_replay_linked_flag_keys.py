import json
from io import StringIO
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models import Team

from products.feature_flags.backend.management.commands import repair_replay_linked_flag_keys as repair_command
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.test.replay_gate_fixtures import set_linked_flag, set_trigger_groups


class TestRepairReplayLinkedFlagKeys(BaseTest):
    def _run(self, *args: str, teams: list[Team]) -> dict[str, Any]:
        # Scope to this test's teams: the local test DB is reused across suites and can carry
        # leftover rows from other tests.
        out = StringIO()
        call_command(
            "repair_replay_linked_flag_keys",
            "--json",
            "--team-id",
            *[str(team.id) for team in teams],
            *args,
            stdout=out,
        )
        return json.loads(out.getvalue())

    def test_repairs_a_stale_key_and_is_idempotent(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        set_linked_flag(self.team, {"id": flag.id, "key": "replay-gate", "variant": "control"})

        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {"repaired": 1}
        assert report["repairs"] == [
            {
                "outcome": "repaired",
                "location": "linked_flag",
                "team_id": self.team.id,
                "project_id": self.team.project_id,
                "stored_flag": {"id": flag.id, "key": "replay-gate", "variant": "control"},
                "flag_id": flag.id,
                "old_key": "replay-gate",
                "new_key": "replay-gate-v2",
            }
        ]
        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {
            "id": flag.id,
            "key": "replay-gate-v2",
            "variant": "control",
        }

        assert self._run("--live-run", teams=[self.team])["outcomes"] == {"already_correct": 1}

    def test_reports_the_repair_without_writing_unless_asked(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        set_linked_flag(self.team, {"id": flag.id, "key": "replay-gate"})

        report = self._run(teams=[self.team])

        assert report["dry_run"] is True
        assert report["outcomes"] == {"repaired": 1}
        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": flag.id, "key": "replay-gate"}

    def _assert_link_survives(self, linked_flag: dict[str, Any], outcome: str) -> None:
        # Clearing an unrepairable link would remove the recording gate, taking a team from
        # recording a filtered subset to recording every session.
        set_linked_flag(self.team, linked_flag)

        # `--live-run` so the row surviving proves the command declined to rewrite it, rather than
        # just proving dry-run writes nothing.
        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {outcome: 1}
        assert report["unrepairable"][0]["outcome"] == outcome
        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == linked_flag

    @parameterized.expand(
        [
            ("missing_id", {"key": "replay-gate"}, "malformed"),
            # `bool` subclasses `int`, so without the explicit guard this would repair against flag 1.
            ("bool_id", {"id": True, "key": "replay-gate"}, "malformed"),
            ("non_numeric_id", {"id": "abc", "key": "replay-gate"}, "malformed"),
            ("flag_missing", {"id": 987654321, "key": "replay-gate"}, "flag_missing"),
        ]
    )
    def test_leaves_malformed_or_dangling_links_alone(
        self, _name: str, linked_flag: dict[str, Any], outcome: str
    ) -> None:
        self._assert_link_survives(linked_flag, outcome)

    @parameterized.expand(
        [
            ("flag_soft_deleted", True, True, "flag_soft_deleted"),
            ("flag_in_other_project", False, False, "flag_in_other_project"),
        ]
    )
    def test_leaves_links_to_unusable_flags_alone(
        self, _name: str, same_project: bool, deleted: bool, outcome: str
    ) -> None:
        flag_team = self.team if same_project else Team.objects.create(organization=self.organization)
        flag = FeatureFlag.objects.create(team=flag_team, created_by=self.user, key="replay-gate-v2", deleted=deleted)
        self._assert_link_survives({"id": flag.id, "key": "replay-gate"}, outcome)

    def test_repairs_a_sibling_team_linking_another_teams_flag(self) -> None:
        sibling_team = Team.objects.create(organization=self.organization, project=self.team.project)
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        set_linked_flag(sibling_team, {"id": flag.id, "key": "replay-gate"})

        report = self._run("--live-run", teams=[sibling_team])

        assert report["outcomes"] == {"repaired": 1}
        sibling_team.refresh_from_db()
        assert sibling_team.session_recording_linked_flag == {"id": flag.id, "key": "replay-gate-v2"}

    def test_a_rename_landing_mid_scan_is_not_written_back(self) -> None:
        # Every flag key is read once per chunk, before the first team row of that chunk is
        # locked. A rename in that window relinks the team on its own, so writing the key the
        # chunk read leaves the team gating on a key no flag holds, which is the failure this
        # command exists to repair.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-b")
        set_linked_flag(self.team, {"id": flag.id, "key": "gate-a"})

        real_save = repair_command.save_replay_gate_rewrites

        def rename_then_save(team_id: int, compute: Any) -> None:
            flag.key = "gate-c"
            with self.captureOnCommitCallbacks(execute=True):
                flag.save()
            real_save(team_id, compute)

        with patch.object(repair_command, "save_replay_gate_rewrites", side_effect=rename_then_save):
            report = self._run("--live-run", teams=[self.team])

        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": flag.id, "key": "gate-c"}
        # The relink did the write, so this run has nothing left to repair and claims none.
        assert report["repairs"] == []
        assert report["outcomes"] == {"already_correct": 1}

    @parameterized.expand([("a_current_key", "other-current"), ("a_stale_key", "other-stale")])
    def test_a_repoint_mid_scan_is_reported_as_changed_rather_than_repaired(
        self, _name: str, repointed_key: str
    ) -> None:
        # An admin can send the gate to a different flag between the chunk read and the lock.
        # That edit is not this command's to touch, and reporting a repair here would name a key
        # the team does not hold, on a flag it no longer points at. It is reported all the same,
        # and whether the key that lands happens to be current makes no difference: this run read
        # it against no flag, so counting it correct would hide a team that is still not
        # recording.
        stale_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-current")
        other_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="other-current")
        set_linked_flag(self.team, {"id": stale_flag.id, "key": "gate-stale"})
        repointed = {"id": other_flag.id, "key": repointed_key}

        real_save = repair_command.save_replay_gate_rewrites

        def repoint_then_save(team_id: int, compute: Any) -> None:
            admin = Team.objects.get(pk=team_id)
            admin.session_recording_linked_flag = repointed
            admin.save()
            real_save(team_id, compute)

        with patch.object(repair_command, "save_replay_gate_rewrites", side_effect=repoint_then_save):
            report = self._run("--live-run", teams=[self.team])

        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == repointed
        assert report["repairs"] == []
        assert report["outcomes"] == {"changed_mid_scan": 1}
        assert report["unrepairable"][0]["location"] == "linked_flag"

    def test_a_flag_hard_deleted_at_write_time_writes_nothing(self) -> None:
        # The key is read again inside the team's row lock. A hard delete landing in that window
        # leaves no key to adopt, and writing the None it reads would store a gate the SDKs
        # cannot resolve, which stops the team recording.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-current")
        set_linked_flag(self.team, {"id": flag.id, "key": "gate-stale"})

        real_save = repair_command.save_replay_gate_rewrites

        def hard_delete_then_save(team_id: int, compute: Any) -> None:
            FeatureFlag.objects_including_soft_deleted.filter(pk=flag.id).delete()
            real_save(team_id, compute)

        with patch.object(repair_command, "save_replay_gate_rewrites", side_effect=hard_delete_then_save):
            report = self._run("--live-run", teams=[self.team])

        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": flag.id, "key": "gate-stale"}
        assert report["repairs"] == []
        assert report["outcomes"] == {"flag_missing": 1}

    def test_a_team_row_gone_at_write_time_is_not_reported_as_a_missing_flag(self) -> None:
        # `save_replay_gate_rewrites` skips the rewrite when the team row is gone, which reads the
        # same as a flag that resolved to nothing. Filing it under flag_missing sends whoever runs
        # the repair looking at the wrong row.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="gate-live")
        set_linked_flag(self.team, {"id": flag.id, "key": "gate-stale"})
        command = repair_command.Command()
        findings = command._scan_linked_flag(self.team, command._load_flags([self.team]))

        written = command._write_repairs(self.team.pk + 10_000_000, findings)

        assert [finding.outcome for finding in written] == [repair_command.Outcome.TEAM_MISSING]
        # A key it never wrote has no place in the report.
        assert "new_key" not in written[0].as_report_row()

    def test_repairs_every_team_across_chunk_boundaries(self) -> None:
        # A chunk size smaller than the number of scanned teams forces _iter_team_chunks through
        # more than one page; every team must still be repaired, not just the first chunk's.
        teams = [self.team] + [
            Team.objects.create(organization=self.organization, project=self.team.project) for _ in range(2)
        ]
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        for team in teams:
            set_linked_flag(team, {"id": flag.id, "key": "replay-gate"})

        report = self._run("--live-run", "--chunk-size", "1", teams=teams)

        assert report["outcomes"] == {"repaired": 3}
        for team in teams:
            team.refresh_from_db()
            assert team.session_recording_linked_flag == {"id": flag.id, "key": "replay-gate-v2"}

    def test_rejects_a_zero_chunk_size(self) -> None:
        # A zero chunk slices to an empty list every time, so the command would report scanning
        # zero teams instead of failing loudly.
        with self.assertRaises(CommandError):
            self._run("--live-run", "--chunk-size", "0", teams=[self.team])

    def test_repairs_a_trigger_group_key_and_names_the_group_it_fixed(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        set_trigger_groups(
            self.team,
            {"events": ["$pageview"]},
            {"flag": {"id": flag.id, "key": "replay-gate", "variant": "control"}},
        )

        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {"repaired": 1}
        assert report["repairs"] == [
            {
                "outcome": "repaired",
                "location": "trigger_group",
                "team_id": self.team.id,
                "project_id": self.team.project_id,
                "group_index": 1,
                "group_id": "group-1",
                "stored_flag": {"id": flag.id, "key": "replay-gate", "variant": "control"},
                "flag_id": flag.id,
                "old_key": "replay-gate",
                "new_key": "replay-gate-v2",
            }
        ]
        self.team.refresh_from_db()
        assert self.team.session_recording_trigger_groups["groups"][1]["conditions"]["flag"] == {
            "id": flag.id,
            "key": "replay-gate-v2",
            "variant": "control",
        }

    def test_reports_a_group_that_stores_no_id_of_its_own(self) -> None:
        # `group_index: 0` and `group_id: null` are how a human finds the group in a team with
        # several. One is falsy and the other is None, so both have to survive into the row.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        self.team.session_recording_trigger_groups = {
            "version": 2,
            "groups": [{"sampleRate": 1, "conditions": {"flag": {"id": flag.id, "key": "replay-gate"}}}],
        }
        self.team.save()

        report = self._run("--live-run", teams=[self.team])

        assert report["repairs"] == [
            {
                "outcome": "repaired",
                "location": "trigger_group",
                "team_id": self.team.id,
                "project_id": self.team.project_id,
                "group_index": 0,
                "group_id": None,
                "stored_flag": {"id": flag.id, "key": "replay-gate"},
                "flag_id": flag.id,
                "old_key": "replay-gate",
                "new_key": "replay-gate-v2",
            }
        ]

    def test_reports_an_unreadable_trigger_groups_column_without_touching_it(self) -> None:
        # The column is schemaless, so a row predating the validator can hold anything. Indexing
        # into it would abort a fleet-wide sweep part way, after it had already written.
        stored = {"version": 2, "groups": "not-a-list"}
        self.team.session_recording_trigger_groups = stored
        self.team.save()

        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {"malformed": 1}
        assert report["unrepairable"] == [
            {
                "outcome": "malformed",
                "location": "trigger_groups_column",
                "team_id": self.team.id,
                "project_id": self.team.project_id,
                "stored_flag": stored,
            }
        ]
        self.team.refresh_from_db()
        assert self.team.session_recording_trigger_groups == stored

    @parameterized.expand([("object_with_no_key", {"id": 1}), ("empty_key", "")])
    def test_reports_a_trigger_group_reference_with_no_readable_key(self, _name: str, stored_flag: Any) -> None:
        # The key is what the SDK resolves, so a reference without one gates nothing. Pinned
        # because the ladder gives up here rather than falling back to the stored id.
        set_trigger_groups(self.team, {"flag": stored_flag})
        stored_before = self.team.session_recording_trigger_groups

        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {"malformed": 1}
        assert report["unrepairable"][0]["location"] == "trigger_group"
        self.team.refresh_from_db()
        assert self.team.session_recording_trigger_groups == stored_before

    def test_reports_a_bare_key_naming_no_flag_without_touching_it(self) -> None:
        # A bare key stores no id, so nothing records which flag it meant. Guessing a rewrite would
        # move the gate onto an unrelated flag, and clearing it would record every session.
        set_trigger_groups(self.team, {"flag": "replay-gate"})
        stored_before = self.team.session_recording_trigger_groups

        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {"key_unresolvable": 1}
        assert report["unrepairable"][0]["location"] == "trigger_group"
        assert report["unrepairable"][0]["stored_flag"] == "replay-gate"
        self.team.refresh_from_db()
        assert self.team.session_recording_trigger_groups == stored_before

    @parameterized.expand(
        [
            ("bare_key_resolves", {"flag": "replay-gate"}, {"already_correct": 1}),
            # Most groups gate on events or URLs. Counting those as references would bury the ones
            # that actually need a human.
            ("group_gates_on_no_flag", {"events": ["$pageview"]}, {}),
        ]
    )
    def test_stays_quiet_about_healthy_trigger_groups(
        self, _name: str, conditions: dict[str, Any], expected_outcomes: dict[str, int]
    ) -> None:
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate")
        set_trigger_groups(self.team, conditions)

        assert self._run("--live-run", teams=[self.team])["outcomes"] == expected_outcomes

    def test_repairs_one_group_without_moving_a_sibling_it_could_not_resolve(self) -> None:
        # Both groups name the same stale key, but only one stores an id to repair from. Moving the
        # other would rewrite a reference the report hands to a human as untouched.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        set_trigger_groups(
            self.team,
            {"flag": {"id": flag.id, "key": "replay-gate"}},
            {"flag": "replay-gate"},
        )

        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {"repaired": 1, "key_unresolvable": 1}
        self.team.refresh_from_db()
        groups = self.team.session_recording_trigger_groups["groups"]
        assert groups[0]["conditions"]["flag"] == {"id": flag.id, "key": "replay-gate-v2"}
        assert groups[1]["conditions"]["flag"] == "replay-gate"

    def test_repairs_groups_sharing_a_stale_key_to_their_own_flags(self) -> None:
        # The groups' ids name different flags. Resolving the stale key once per team would point
        # both gates at whichever flag was looked up first, silently retargeting the other.
        alpha = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="alpha-now")
        beta = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="beta-now")
        set_trigger_groups(
            self.team,
            {"flag": {"id": alpha.id, "key": "shared-stale"}},
            {"flag": {"id": beta.id, "key": "shared-stale"}},
        )

        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {"repaired": 2}
        assert [repair["new_key"] for repair in report["repairs"]] == ["alpha-now", "beta-now"]
        self.team.refresh_from_db()
        groups = self.team.session_recording_trigger_groups["groups"]
        assert groups[0]["conditions"]["flag"] == {"id": alpha.id, "key": "alpha-now"}
        assert groups[1]["conditions"]["flag"] == {"id": beta.id, "key": "beta-now"}

    @parameterized.expand(
        [
            ("flag_soft_deleted", True, True, "flag_soft_deleted"),
            ("flag_in_other_project", False, False, "flag_in_other_project"),
        ]
    )
    def test_leaves_trigger_groups_naming_unusable_flags_alone(
        self, _name: str, same_project: bool, deleted: bool, outcome: str
    ) -> None:
        # Reached only once the stored key fails to resolve, so this is a different ladder from the
        # linked flag column's and needs its own cover.
        flag_team = self.team if same_project else Team.objects.create(organization=self.organization)
        flag = FeatureFlag.objects.create(team=flag_team, created_by=self.user, key="replay-gate-v2", deleted=deleted)
        set_trigger_groups(self.team, {"flag": {"id": flag.id, "key": "replay-gate"}})
        stored_before = self.team.session_recording_trigger_groups

        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {outcome: 1}
        self.team.refresh_from_db()
        assert self.team.session_recording_trigger_groups == stored_before

    @parameterized.expand([("gates_on_events", False), ("holds_the_same_reference", True)])
    def test_a_group_added_mid_scan_does_not_shift_the_repair_onto_its_neighbour(
        self, _name: str, inserted_group_duplicates_the_reference: bool
    ) -> None:
        # Groups are rewritten by index, and an admin can add one ahead of the repaired group
        # between the chunk read and the lock. Writing the scanned index then would move the gate
        # of a group this run never looked at. A sibling holding the same reference takes the
        # rewrite while the report still names the scanned group, which stays stale.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        stored_flag = {"id": flag.id, "key": "replay-gate"}
        set_trigger_groups(self.team, {"flag": stored_flag})
        scanned_groups = self.team.session_recording_trigger_groups["groups"]
        inserted_conditions: dict[str, Any] = (
            {"flag": stored_flag} if inserted_group_duplicates_the_reference else {"events": ["$pageview"]}
        )
        # Built by hand rather than through the fixture, because an admin inserting a group leaves
        # the ids of the groups it pushes along alone.
        after_insert = [
            {"id": "group-inserted", "sampleRate": 1, "conditions": {"matchType": "any", **inserted_conditions}},
            *scanned_groups,
        ]

        real_save = repair_command.save_replay_gate_rewrites

        def prepend_group_then_save(team_id: int, compute: Any) -> None:
            admin = Team.objects.get(pk=team_id)
            admin.session_recording_trigger_groups = {"version": 2, "groups": after_insert}
            admin.save()
            real_save(team_id, compute)

        with patch.object(repair_command, "save_replay_gate_rewrites", side_effect=prepend_group_then_save):
            report = self._run("--live-run", teams=[self.team])

        assert report["repairs"] == []
        assert report["outcomes"] == {"changed_mid_scan": 1}
        self.team.refresh_from_db()
        # Every group still stale, and reported as untouched, so the next run repairs them where
        # they now sit.
        assert self.team.session_recording_trigger_groups["groups"] == after_insert

    def test_repairs_both_kinds_of_reference_in_one_pass(self) -> None:
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        self.team.session_recording_linked_flag = {"id": flag.id, "key": "replay-gate"}
        set_trigger_groups(self.team, {"flag": {"id": flag.id, "key": "replay-gate"}})

        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {"repaired": 2}
        assert {finding["location"] for finding in report["repairs"]} == {"linked_flag", "trigger_group"}
        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": flag.id, "key": "replay-gate-v2"}
        assert self.team.session_recording_trigger_groups["groups"][0]["conditions"]["flag"] == {
            "id": flag.id,
            "key": "replay-gate-v2",
        }
