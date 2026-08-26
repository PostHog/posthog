import json
from io import StringIO
from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.models import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestRepairReplayLinkedFlagKeys(BaseTest):
    def _link_flag(self, team: Team, linked_flag: dict[str, Any] | None) -> None:
        team.session_recording_linked_flag = linked_flag
        team.save()

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
        self._link_flag(self.team, {"id": flag.id, "key": "replay-gate", "variant": "control"})

        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {"repaired": 1}
        assert report["repairs"] == [
            {
                "outcome": "repaired",
                "team_id": self.team.id,
                "project_id": self.team.project_id,
                "linked_flag": {"id": flag.id, "key": "replay-gate", "variant": "control"},
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
        # Writing has to be opted into: a bare run rewrites every team's replay config and
        # enqueues a RemoteConfig rebuild per row.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        self._link_flag(self.team, {"id": flag.id, "key": "replay-gate"})

        report = self._run(teams=[self.team])

        assert report["dry_run"] is True
        assert report["outcomes"] == {"repaired": 1}
        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == {"id": flag.id, "key": "replay-gate"}

    @parameterized.expand(
        [
            ("flag_soft_deleted", "flag_soft_deleted"),
            ("flag_in_other_project", "flag_in_other_project"),
            ("flag_missing", "flag_missing"),
            ("missing_id", "malformed"),
            ("bool_id", "malformed"),
            ("non_numeric_id", "malformed"),
        ]
    )
    def test_leaves_links_it_cannot_safely_repair_alone(self, case: str, outcome: str) -> None:
        # Clearing an unrepairable link would remove the recording gate, taking a team from
        # recording a filtered subset to recording every session. `bool` subclasses `int`, so
        # without the explicit guard `{"id": true}` would repair the team against flag 1.
        linked_flag: dict[str, Any]
        if case == "flag_missing":
            linked_flag = {"id": 987654321, "key": "replay-gate"}
        elif case == "missing_id":
            linked_flag = {"key": "replay-gate"}
        elif case == "bool_id":
            linked_flag = {"id": True, "key": "replay-gate"}
        elif case == "non_numeric_id":
            linked_flag = {"id": "abc", "key": "replay-gate"}
        else:
            flag_team = (
                self.team if case == "flag_soft_deleted" else Team.objects.create(organization=self.organization)
            )
            flag = FeatureFlag.objects.create(
                team=flag_team,
                created_by=self.user,
                key="replay-gate-v2",
                deleted=case == "flag_soft_deleted",
            )
            linked_flag = {"id": flag.id, "key": "replay-gate"}
        self._link_flag(self.team, linked_flag)

        # `--live-run` so the row surviving proves the command declined to rewrite it, rather than
        # just proving dry-run writes nothing.
        report = self._run("--live-run", teams=[self.team])

        assert report["outcomes"] == {outcome: 1}
        assert report["unrepairable"][0]["outcome"] == outcome
        self.team.refresh_from_db()
        assert self.team.session_recording_linked_flag == linked_flag

    def test_repairs_a_sibling_team_linking_another_teams_flag(self) -> None:
        sibling_team = Team.objects.create(organization=self.organization, project=self.team.project)
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-gate-v2")
        self._link_flag(sibling_team, {"id": flag.id, "key": "replay-gate"})

        report = self._run("--live-run", teams=[sibling_team])

        assert report["outcomes"] == {"repaired": 1}
        sibling_team.refresh_from_db()
        assert sibling_team.session_recording_linked_flag == {"id": flag.id, "key": "replay-gate-v2"}
