from io import StringIO
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.db import OperationalError
from django.test import override_settings

from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Project, Team

from products.managed_warehouse.backend import project_moves
from products.managed_warehouse.backend.facade.api import commit_project_move_out, project_move_out
from products.managed_warehouse.backend.facade.contracts import CPUnavailableError, ProjectMoveOut
from products.managed_warehouse.backend.models import DuckgresServer, ManagedWarehouseSourceLifecycle
from products.managed_warehouse.backend.presentation.hogtower import TranslatedResponse
from products.managed_warehouse.backend.tasks.tasks import repeat_project_move_out, restore_project_move_out


class FakeHogtower:
    """Serves the move's hogtower calls (v1 vocabulary) from in-memory rows keyed by warehouse."""

    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self.rows = rows
        self.failing: set[tuple[str, str]] = set()
        self.calls: list[tuple[str, str, str, Any]] = []
        self.on_call: Any = None

    def __call__(self, method: str, organization_id: str, path: str, *, json_body: Any = None, **_: Any):
        self.calls.append((method, organization_id, path, json_body))
        if self.on_call is not None:
            self.on_call(method, path)
        if (method, path) in self.failing:
            return TranslatedResponse(503, {"error": "unavailable"})
        if (method, path) == ("GET", "teams"):
            return TranslatedResponse(
                200, {"teams": [{**r, "org_id": o} for o, rows in self.rows.items() for r in rows]}
            )
        rows = self.rows.get(organization_id)
        if (method, path) == ("POST", "/moved-teams"):
            removed = [row for row in rows or [] if row["team_id"] in json_body["team_ids"]]
            if rows is not None:
                self.rows[organization_id] = [row for row in rows if row not in removed]
            return TranslatedResponse(200, {"removed": removed})
        if rows is None:
            return TranslatedResponse(404, {"error": "warehouse not found"})
        if (method, path) == ("GET", "/teams"):
            return TranslatedResponse(200, {"teams": [dict(row) for row in rows]})
        if (method, path) == ("POST", "/teams"):
            kept = [row for row in rows if row["team_id"] != json_body["team_id"]]
            self.rows[organization_id] = [*kept, dict(json_body)]
            return TranslatedResponse(200, dict(json_body))
        raise AssertionError(f"unexpected call {method} {path}")

    def paths(self) -> list[tuple[str, str, str]]:
        return [(method, org, path) for method, org, path, _ in self.calls]


@override_settings(HOGTOWER_API_URL="http://hogtower.invalid")
class TestProjectMoveOut(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.other_org = Organization.objects.create(name="Receiving org")
        OrganizationMembership.objects.create(
            user=self.user, organization=self.other_org, level=OrganizationMembership.Level.ADMIN
        )
        self.org_id = str(self.organization.id)
        self.row = {
            "org_id": self.org_id,
            "team_id": self.team.pk,
            "schema_name": "acme",
            "enabled": True,
            "backfill_enabled": False,
            "earliest_event_date": "2024-01-02",
        }
        self.fake = FakeHogtower({self.org_id: [dict(self.row)]})
        self.enqueue = MagicMock()
        self.enqueue_restore = MagicMock()
        for patcher in (
            patch("products.managed_warehouse.backend.presentation.hogtower.request", new=self.fake),
            patch.object(repeat_project_move_out, "apply_async", new=self.enqueue),
            patch.object(restore_project_move_out, "apply_async", new=self.enqueue_restore),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _give_org_warehouse_state(self) -> None:
        ManagedWarehouseSourceLifecycle.objects.create(organization=self.organization)

    def _move(self):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                f"/api/projects/{self.project.id}/change_organization/", {"organization_id": str(self.other_org.id)}
            )

    def _project_org(self) -> str:
        return str(Project.objects.get(pk=self.project.pk).organization_id)

    def test_an_org_without_warehouse_state_makes_no_call_but_still_enqueues_the_repeat(self) -> None:
        res = self._move()

        assert res.status_code == status.HTTP_200_OK, res.json()
        assert self.fake.calls == []
        self.enqueue.assert_called_once_with(args=[self.org_id, [self.team.pk]], countdown=600)

    def test_a_move_removes_the_rows_before_its_commit_and_again_after_it(self) -> None:
        self._give_org_warehouse_state()
        org_at_removal: list[str] = []

        def record_project_org(method: str, path: str) -> None:
            if path == "/moved-teams":
                org_at_removal.append(self._project_org())

        self.fake.on_call = record_project_org

        res = self._move()

        assert res.status_code == status.HTTP_200_OK, res.json()
        assert self.fake.paths() == [
            ("GET", self.org_id, "/teams"),
            ("POST", self.org_id, "/moved-teams"),
            ("POST", self.org_id, "/moved-teams"),
        ]
        assert org_at_removal == [self.org_id, str(self.other_org.id)]
        assert self.fake.rows[self.org_id] == []
        self.enqueue.assert_called_once_with(args=[self.org_id, [self.team.pk]], countdown=600)

    def test_a_failed_removal_refuses_the_move_and_puts_the_rows_back(self) -> None:
        DuckgresServer.objects.create(organization=self.organization, host="h", username="root", password="x")
        self.fake.failing.add(("POST", "/moved-teams"))

        res = self._move()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["detail"] == project_moves.TRY_AGAIN
        assert self._project_org() == self.org_id
        assert self.fake.calls[-1] == ("POST", self.org_id, "/teams", self.row)
        self.enqueue.assert_not_called()

    def test_a_failed_restore_is_retried_by_a_task(self) -> None:
        self._give_org_warehouse_state()
        self.fake.failing.update({("POST", "/moved-teams"), ("POST", "/teams")})

        res = self._move()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        self.enqueue_restore.assert_called_once_with(args=[self.project.pk, self.org_id, [self.row]], countdown=60)
        self.fake.rows[self.org_id] = []  # the removal applied after all
        with self.assertRaises(CPUnavailableError):
            restore_project_move_out(self.project.pk, self.org_id, [self.row])

        self.fake.failing.clear()
        restore_project_move_out(self.project.pk, self.org_id, [self.row])
        assert self.fake.rows[self.org_id] == [self.row]

    def test_an_error_in_the_restore_retries_every_row(self) -> None:
        self._give_org_warehouse_state()

        with patch.object(project_moves, "restore_rows", side_effect=OperationalError("lock timeout")):
            with self.assertRaises(RuntimeError):
                with project_move_out(self.project.pk, self.organization.id, {self.team.pk: self.organization.id}):
                    raise RuntimeError("the move failed")

        self.enqueue_restore.assert_called_once_with(args=[self.project.pk, self.org_id, [self.row]], countdown=60)

    def test_the_restore_task_skips_teams_the_org_no_longer_owns(self) -> None:
        self._give_org_warehouse_state()
        self.fake.rows[self.org_id] = []
        deleted_team_row = {**self.row, "team_id": 999999, "schema_name": "gone"}

        restore_project_move_out(self.project.pk, self.org_id, [self.row, deleted_team_row])
        assert self.fake.rows[self.org_id] == [self.row]

        # The move committed after all: no restore, and the after-commit repeats run instead.
        self.fake.rows[self.org_id] = []
        calls_before = len(self.fake.calls)
        Project.objects.filter(pk=self.project.pk).update(organization=self.other_org)
        Team.objects.filter(pk=self.team.pk).update(organization=self.other_org)
        restore_project_move_out(self.project.pk, self.org_id, [self.row])
        assert self.fake.calls[calls_before:] == [("POST", self.org_id, "/moved-teams", {"team_ids": [self.team.pk]})]
        self.enqueue.assert_called_once_with(args=[self.org_id, [self.team.pk]], countdown=600)

    def test_an_unreadable_warehouse_refuses_the_move_without_removing_anything(self) -> None:
        self._give_org_warehouse_state()
        self.fake.failing.add(("GET", "/teams"))

        res = self._move()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert self.fake.paths() == [("GET", self.org_id, "/teams")]
        assert self._project_org() == self.org_id

    def test_a_failure_inside_the_transaction_puts_the_rows_back(self) -> None:
        self._give_org_warehouse_state()

        with patch("posthog.api.project.log_activity", side_effect=RuntimeError("boom")):
            res = self._move()

        assert res.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        assert self._project_org() == self.org_id
        assert self.fake.rows[self.org_id] == [self.row]
        self.enqueue.assert_not_called()
        self.enqueue_restore.assert_not_called()

    def test_an_error_after_the_commit_does_not_put_the_rows_back(self) -> None:
        self._give_org_warehouse_state()

        with self.assertRaises(RuntimeError):
            with project_move_out(self.project.pk, self.organization.id, {self.team.pk: self.organization.id}):
                Project.objects.filter(pk=self.project.pk).update(organization=self.other_org)
                raise RuntimeError("after the commit")

        assert ("POST", self.org_id, "/teams") not in self.fake.paths()
        assert self.fake.rows[self.org_id] == []
        self.enqueue.assert_called_once_with(args=[self.org_id, [self.team.pk]], countdown=600)
        self.enqueue_restore.assert_not_called()

    def test_a_concurrent_move_during_the_restore_removes_the_rows_again(self) -> None:
        self._give_org_warehouse_state()

        def concurrent_move_commits(method: str, path: str) -> None:
            if (method, path) == ("POST", "/teams"):
                Project.objects.filter(pk=self.project.pk).update(organization=self.other_org)
                Team.objects.filter(pk=self.team.pk).update(organization=self.other_org)

        with self.assertRaises(RuntimeError):
            with project_move_out(self.project.pk, self.organization.id, {self.team.pk: self.organization.id}):
                self.fake.on_call = concurrent_move_commits
                raise RuntimeError("the move failed")

        assert self.fake.paths()[-2:] == [("POST", self.org_id, "/teams"), ("POST", self.org_id, "/moved-teams")]
        assert self.fake.rows[self.org_id] == []

    def test_an_environment_in_another_organization_refuses_the_move(self) -> None:
        self._give_org_warehouse_state()
        stray_org = Organization.objects.create(name="Stray")
        Team.objects.create(organization=stray_org, project=self.project, name="Stray environment")

        res = self._move()

        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "more than one organization" in res.json()["detail"]
        assert self.fake.calls == []
        assert self._project_org() == self.org_id

    def test_an_environment_in_another_organization_moves_when_no_org_has_warehouse_state(self) -> None:
        stray_org = Organization.objects.create(name="Stray")
        Team.objects.create(organization=stray_org, project=self.project, name="Stray environment")

        res = self._move()

        assert res.status_code == status.HTTP_200_OK, res.json()
        assert self.fake.calls == []

    def test_more_than_100_environments_are_refused(self) -> None:
        self._give_org_warehouse_state()
        teams = dict.fromkeys(range(1, 102), self.organization.id)

        with project_move_out(self.project.pk, self.organization.id, teams) as move:
            assert move.refusal == "Projects with more than 100 environments can't be moved."
        assert self.fake.calls == []

    def test_a_move_that_committed_meanwhile_is_refused_under_the_lock(self) -> None:
        move = ProjectMoveOut(project_id=self.project.pk, organization_id=self.org_id, guarded=True)

        assert (
            commit_project_move_out(move, self.other_org.id, {self.team.pk: self.other_org.id}) == project_moves.CHANGED
        )
        assert commit_project_move_out(move, self.organization.id, {self.team.pk: self.org_id}) is None

    def test_the_delayed_task_removes_a_late_row_but_keeps_a_team_that_moved_back(self) -> None:
        self._give_org_warehouse_state()
        moved_back = Team.objects.create(organization=self.organization, project=self.project, name="Moved back")
        Team.objects.filter(pk=self.team.pk).update(organization=self.other_org)
        back_row = {**self.row, "team_id": moved_back.pk, "schema_name": "back"}
        self.fake.rows[self.org_id] = [dict(self.row), back_row]

        repeat_project_move_out(self.org_id, [self.team.pk, moved_back.pk])

        assert self.fake.calls == [("POST", self.org_id, "/moved-teams", {"team_ids": [self.team.pk]})]
        assert self.fake.rows[self.org_id] == [back_row]

    def test_the_delayed_task_raises_for_a_retry_when_hogtower_does_not_confirm(self) -> None:
        self._give_org_warehouse_state()
        Team.objects.filter(pk=self.team.pk).update(organization=self.other_org)
        self.fake.failing.add(("POST", "/moved-teams"))

        with self.assertRaises(CPUnavailableError):
            repeat_project_move_out(self.org_id, [self.team.pk])

        assert self.fake.rows[self.org_id] == [self.row]

    def test_the_delayed_task_does_nothing_for_an_org_without_warehouse_state(self) -> None:
        repeat_project_move_out(self.org_id, [self.team.pk])

        assert self.fake.calls == []

    def test_the_command_lists_and_removes_rows_left_in_both_directions(self) -> None:
        self._give_org_warehouse_state()
        third_org = Organization.objects.create(name="Third")
        left_behind = Team.objects.create(organization=self.other_org, project=self.project, name="Moved out")
        arrived = Team.objects.create(organization=self.organization, project=self.project, name="Moved in")
        deleted_team_row = {"team_id": 999999, "schema_name": "gone"}
        self.fake.rows = {
            self.org_id: [dict(self.row), {"team_id": left_behind.pk, "schema_name": "out"}, deleted_team_row],
            str(third_org.id): [{"team_id": arrived.pk, "schema_name": "in"}],
        }

        out = StringIO()
        call_command("managed_warehouse_moved_rows", "--org", self.org_id, stdout=out)
        assert f"warehouse {self.org_id}: teams [{left_behind.pk}]" in out.getvalue()
        assert f"warehouse {third_org.id}: teams [{arrived.pk}]" in out.getvalue()
        assert not any(path == "/moved-teams" for _, _, path in self.fake.paths())

        call_command("managed_warehouse_moved_rows", "--org", self.org_id, "--remove", stdout=StringIO())
        assert self.fake.rows == {self.org_id: [self.row, deleted_team_row], str(third_org.id): []}

    def test_the_command_refuses_an_org_without_warehouse_state(self) -> None:
        with self.assertRaises(CommandError):
            call_command("managed_warehouse_moved_rows", "--org", self.org_id, stdout=StringIO())
        assert self.fake.calls == []
