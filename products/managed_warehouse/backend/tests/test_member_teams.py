from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

import requests

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.managed_warehouse.backend import member_teams, signals
from products.managed_warehouse.backend.models import DuckgresServer

BASE = "http://hogtower.invalid"
REQUEST = "products.managed_warehouse.backend.presentation.hogtower.internal_requests.request"
ENABLED = override_settings(
    HOGTOWER_API_URL=f"{BASE}/",
    HOGTOWER_INTERNAL_SECRET="ht-secret",
    HOGTOWER_MEMBER_TEAMS_PUSH_ENABLED=True,
)


def _http(status_code: int, body: object) -> MagicMock:
    resp = MagicMock(status_code=status_code, text=str(body))
    resp.json.return_value = body
    return resp


class _MemberTeamsTest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.member = User.objects.create_and_join(self.organization, "member@posthog.com", "testtest")
        self.membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)

    def _rule(self, team: Team, resource: str, level: str, **kwargs) -> AccessControl:
        return AccessControl.objects.create(team=team, resource=resource, access_level=level, **kwargs)


class TestMemberTeams(_MemberTeamsTest):
    def test_default_access_is_write_on_every_visible_team(self) -> None:
        other = Team.objects.create(organization=self.organization, name="other")
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "write", other.id: "write"}

    def test_a_warehouse_viewer_reads_and_none_leaves_the_team_out(self) -> None:
        read_only = Team.objects.create(organization=self.organization, name="read only")
        hidden = Team.objects.create(organization=self.organization, name="hidden")
        self._rule(read_only, "warehouse_objects", "viewer")
        self._rule(hidden, "warehouse_objects", "none")
        assert member_teams.member_teams(self.organization, self.member) == {
            self.team.id: "write",
            read_only.id: "read",
        }

    def test_a_private_project_is_left_out(self) -> None:
        private = Team.objects.create(organization=self.organization, name="private")
        self._rule(private, "project", "none", resource_id=str(private.id))
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "write"}

    def test_an_explicit_member_rule_beats_the_default(self) -> None:
        self._rule(self.team, "warehouse_objects", "viewer")
        self._rule(self.team, "warehouse_objects", "editor", organization_member=self.membership)
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "write"}

    def test_an_organization_admin_writes_whatever_the_rules_say(self) -> None:
        self._rule(self.team, "warehouse_objects", "viewer")
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "write"}

    def test_another_organizations_teams_never_appear(self) -> None:
        elsewhere = Organization.objects.create(name="elsewhere")
        Team.objects.create(organization=elsewhere, name="theirs")
        OrganizationMembership.objects.create(organization=elsewhere, user=self.member)
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "write"}


@ENABLED
class TestPushMember(_MemberTeamsTest):
    def _push(self, response: MagicMock | Exception, user_uuid: str | None = None) -> tuple[str, MagicMock]:
        mock = MagicMock(side_effect=response) if isinstance(response, Exception) else MagicMock(return_value=response)
        with patch(REQUEST, mock):
            outcome = member_teams.push_member(str(self.organization.id), user_uuid or str(self.member.uuid))
        return outcome, mock

    def test_puts_the_whole_team_set_with_a_version(self) -> None:
        outcome, mock = self._push(_http(200, {"changed": True}))
        assert outcome == "pushed"
        method, url = mock.call_args.args
        assert method == "PUT"
        assert url == f"{BASE}/api/v2/warehouses/{self.organization.id}/members/{self.member.uuid}/teams"
        body = mock.call_args.kwargs["json"]
        assert body["teams"] == {str(self.team.id): "write"}
        assert isinstance(body["version"], int) and body["version"] > 0
        assert mock.call_args.kwargs["headers"] == {"X-Hogtower-Internal-Secret": "ht-secret"}

    def test_versions_increase(self) -> None:
        _, first = self._push(_http(200, {}))
        _, second = self._push(_http(200, {}))
        assert second.call_args.kwargs["json"]["version"] > first.call_args.kwargs["json"]["version"]

    def test_a_member_who_left_is_removed(self) -> None:
        self.membership.delete()
        outcome, mock = self._push(_http(200, {"removed": True}))
        assert outcome == "removed"
        method, url = mock.call_args.args
        assert method == "DELETE"
        assert url == f"{BASE}/api/v2/warehouses/{self.organization.id}/members/{self.member.uuid}"
        assert set(mock.call_args.kwargs["json"]) == {"version"}

    def test_a_deactivated_user_is_removed(self) -> None:
        self.member.is_active = False
        self.member.save()
        outcome, mock = self._push(_http(200, {}))
        assert outcome == "removed"
        assert mock.call_args.args[0] == "DELETE"

    def test_an_unknown_user_is_removed(self) -> None:
        outcome, mock = self._push(_http(200, {}), user_uuid=str(uuid4()))
        assert outcome == "removed"

    def test_409_means_a_newer_push_landed(self) -> None:
        assert self._push(_http(409, {"error": "newer version stored"}))[0] == "superseded"

    def test_404_means_hogtower_has_no_warehouse(self) -> None:
        assert self._push(_http(404, {"error": "warehouse not found"}))[0] == "no_warehouse"

    def test_400_is_logged_and_not_retried(self) -> None:
        assert self._push(_http(400, {"error": "invalid member teams"}))[0] == "rejected"

    def test_a_5xx_raises_for_a_retry(self) -> None:
        with pytest.raises(member_teams.MemberTeamsPushError):
            self._push(_http(503, {"error": "unavailable"}))

    def test_a_transport_error_raises_for_a_retry(self) -> None:
        with pytest.raises(member_teams.MemberTeamsPushError):
            self._push(requests.ConnectionError("refused"))


@ENABLED
class TestReceivers(_MemberTeamsTest):
    def setUp(self) -> None:
        super().setUp()
        DuckgresServer.objects.create(organization=self.organization, host="h", username="u", password="p")
        self.member_push = patch.object(member_teams, "enqueue_member_push").start()
        self.org_push = patch.object(member_teams, "enqueue_organization_push").start()
        self.addCleanup(patch.stopall)

    def test_a_new_member_is_pushed_after_commit(self) -> None:
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            joiner = User.objects.create_and_join(self.organization, "joiner@posthog.com", "testtest")
        self.member_push.assert_not_called()
        for callback in callbacks:
            callback()
        self.member_push.assert_any_call(str(self.organization.id), str(joiner.uuid))

    def test_a_level_change_is_pushed(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.membership.level = OrganizationMembership.Level.ADMIN
            self.membership.save()
        self.member_push.assert_called_once_with(str(self.organization.id), str(self.member.uuid))

    def test_a_removed_member_is_pushed_with_their_uuid(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.membership.delete()
        self.member_push.assert_called_once_with(str(self.organization.id), str(self.member.uuid))

    def test_a_deleted_user_is_pushed_with_their_uuid(self) -> None:
        member_uuid = str(self.member.uuid)
        with self.captureOnCommitCallbacks(execute=True):
            self.member.delete()
        self.member_push.assert_any_call(str(self.organization.id), member_uuid)

    def test_a_deactivated_user_is_pushed(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.member.is_active = False
            self.member.save()
        self.member_push.assert_called_once_with(str(self.organization.id), str(self.member.uuid))

    def test_a_role_membership_is_pushed(self) -> None:
        role = Role.objects.create(name="Analysts", organization=self.organization)
        with self.captureOnCommitCallbacks(execute=True):
            RoleMembership.objects.create(role=role, user=self.member, organization_member=self.membership)
        self.member_push.assert_called_with(str(self.organization.id), str(self.member.uuid))

    def test_project_and_warehouse_rules_push_the_organization(self) -> None:
        for resource in ("project", "warehouse_objects"):
            self.org_push.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                rule = AccessControl.objects.create(team=self.team, resource=resource, access_level="viewer")
            self.org_push.assert_called_once_with(str(self.organization.id))
            self.org_push.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                rule.delete()
            self.org_push.assert_called_once_with(str(self.organization.id))

    def test_other_rules_push_nothing(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            AccessControl.objects.create(team=self.team, resource="dashboard", access_level="viewer")
        self.org_push.assert_not_called()

    def test_a_project_created_or_deleted_pushes_the_organization(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            team = Team.objects.create(organization=self.organization, name="new")
        self.org_push.assert_called_once_with(str(self.organization.id))
        self.org_push.reset_mock()
        # Team.delete() needs object storage, which unit tests don't run, so drive the receiver.
        with self.captureOnCommitCallbacks(execute=True):
            signals.team_deleted(Team, team)
        self.org_push.assert_called_once_with(str(self.organization.id))

    def test_no_push_without_a_warehouse(self) -> None:
        DuckgresServer.objects.filter(organization=self.organization).delete()
        with self.captureOnCommitCallbacks(execute=True):
            self.membership.delete()
        self.member_push.assert_not_called()

    def test_no_push_when_disabled(self) -> None:
        with override_settings(HOGTOWER_MEMBER_TEAMS_PUSH_ENABLED=False):
            with self.captureOnCommitCallbacks(execute=True):
                self.membership.delete()
                AccessControl.objects.create(team=self.team, resource="project", access_level="none")
        self.member_push.assert_not_called()
        self.org_push.assert_not_called()

    def test_no_push_without_hogtower(self) -> None:
        with override_settings(HOGTOWER_API_URL=None):
            with self.captureOnCommitCallbacks(execute=True):
                self.membership.delete()
        self.member_push.assert_not_called()


@ENABLED
class TestPushAllAndEnqueue(_MemberTeamsTest):
    def test_push_all_covers_trino_warehouses_of_existing_organizations(self) -> None:
        duckgres_only = Organization.objects.create(name="duckgres only")
        warehouses = [
            {"org_id": str(self.organization.id), "trino": {"catalog": "x"}},
            {"org_id": str(duckgres_only.id)},
            {"org_id": str(uuid4()), "trino": {"catalog": "gone"}},
            {"org_id": "hte2e-1", "trino": {"catalog": "test"}},
        ]
        with (
            patch(REQUEST, return_value=_http(200, {"warehouses": warehouses})),
            patch.object(member_teams, "enqueue_organization_push") as org_push,
        ):
            assert member_teams.push_all() == 1
        org_push.assert_called_once_with(str(self.organization.id), countdown=0)

    def test_push_all_raises_when_hogtower_fails(self) -> None:
        with patch(REQUEST, return_value=_http(503, {})), pytest.raises(member_teams.MemberTeamsPushError):
            member_teams.push_all()

    def test_push_organization_enqueues_every_active_member(self) -> None:
        inactive = User.objects.create_and_join(self.organization, "inactive@posthog.com", "testtest")
        inactive.is_active = False
        inactive.save()
        with (
            patch(REQUEST, return_value=_http(404, {"error": "not found"})),
            patch.object(member_teams, "enqueue_member_push") as member_push,
        ):
            count = member_teams.push_organization(str(self.organization.id))
        pushed = {call.args[1] for call in member_push.call_args_list}
        assert count == 2
        assert pushed == {str(self.user.uuid), str(self.member.uuid)}

    def test_push_organization_also_pushes_members_hogtower_holds_who_left(self) -> None:
        leaver = str(uuid4())
        listed = {"members": [{"user_uuid": str(self.member.uuid)}, {"user_uuid": leaver}]}
        with (
            patch(REQUEST, return_value=_http(200, listed)) as request,
            patch.object(member_teams, "enqueue_member_push") as member_push,
        ):
            count = member_teams.push_organization(str(self.organization.id))
        assert request.call_args.args == ("GET", f"{BASE}/api/v2/warehouses/{self.organization.id}/members")
        assert count == 3
        assert {call.args[1] for call in member_push.call_args_list} == {
            str(self.user.uuid),
            str(self.member.uuid),
            leaver,
        }

    def test_push_organization_still_runs_when_hogtower_cannot_list(self) -> None:
        with (
            patch(REQUEST, side_effect=requests.ConnectionError("refused")),
            patch.object(member_teams, "enqueue_member_push") as member_push,
        ):
            assert member_teams.push_organization(str(self.organization.id)) == 2
        assert member_push.call_count == 2

    def test_a_waiting_push_is_not_enqueued_twice(self) -> None:
        from products.managed_warehouse.backend.tasks import tasks  # noqa: PLC0415

        org, user = str(self.organization.id), str(self.member.uuid)
        with patch.object(tasks.push_warehouse_member_teams, "apply_async") as apply_async:
            member_teams.enqueue_member_push(org, user)
            member_teams.enqueue_member_push(org, user)
            assert apply_async.call_count == 1
            # The push clears the mark when it starts, so a change made during it enqueues again.
            with patch(REQUEST, return_value=_http(200, {})):
                member_teams.push_member(org, user)
            member_teams.enqueue_member_push(org, user)
            assert apply_async.call_count == 2
