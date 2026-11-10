from uuid import UUID, uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

import requests

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User

from products.access_control.backend.facade import testing as access_testing
from products.event_definitions.backend.models import PropertyDefinition
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
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL},
        ]
        self.organization.save()
        self.member = User.objects.create_and_join(self.organization, "member@posthog.com", "testtest")
        self.membership = OrganizationMembership.objects.get(organization=self.organization, user=self.member)

    def _rule(self, team: Team, resource: str, level: str, **kwargs) -> UUID:
        return access_testing.create_access_control(team_id=team.id, resource=resource, access_level=level, **kwargs)

    def _property_rule(self, team: Team, level: str, **kwargs) -> UUID:
        definition = PropertyDefinition.objects.create(team=team, name=f"secret_{uuid4().hex[:8]}", type=1)
        return access_testing.create_property_access_control(
            team_id=team.id, property_definition_id=definition.id, access_level=level, **kwargs
        )


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
        self._rule(self.team, "warehouse_objects", "editor", organization_member_id=self.membership.id)
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "write"}

    def test_an_organization_admin_writes_whatever_the_rules_say(self) -> None:
        self._rule(self.team, "warehouse_objects", "viewer")
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "write"}

    def test_a_hidden_table_view_or_source_withholds_the_team(self) -> None:
        # A team grant covers every table, so it cannot keep one hidden: the team is left out.
        for resource in ("warehouse_table", "warehouse_view", "external_data_source"):
            team = Team.objects.create(organization=self.organization, name=resource)
            self._rule(team, resource, "none", resource_id=str(uuid4()))
            assert team.id not in member_teams.member_teams(self.organization, self.member), resource

    def test_a_member_denied_one_table_loses_the_team(self) -> None:
        self._rule(
            self.team, "warehouse_table", "none", resource_id=str(uuid4()), organization_member_id=self.membership.id
        )
        assert member_teams.member_teams(self.organization, self.member) == {}

    def test_an_object_viewer_rule_lowers_write_to_read(self) -> None:
        self._rule(
            self.team, "warehouse_view", "viewer", resource_id=str(uuid4()), organization_member_id=self.membership.id
        )
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "read"}

    def test_a_higher_object_rule_does_not_raise_the_team_level(self) -> None:
        self._rule(self.team, "warehouse_objects", "viewer")
        self._rule(self.team, "warehouse_table", "editor", resource_id=str(uuid4()))
        self._rule(
            self.team, "warehouse_table", "manager", resource_id=str(uuid4()), organization_member_id=self.membership.id
        )
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "read"}

    def test_a_hidden_object_for_someone_else_does_not_restrict(self) -> None:
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "testtest")
        other_membership = OrganizationMembership.objects.get(organization=self.organization, user=other)
        self._rule(
            self.team, "warehouse_table", "none", resource_id=str(uuid4()), organization_member_id=other_membership.id
        )
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "write"}

    def test_no_access_to_all_sources_withholds_the_team(self) -> None:
        # A table with a source falls back to the all-sources rule.
        self._rule(self.team, "external_data_source", "none")
        assert member_teams.member_teams(self.organization, self.member) == {}

    def _role_editor_and_member_denied_on_one_table(self) -> None:
        table = str(uuid4())
        role_id = access_testing.create_role(organization_id=self.organization.id, name="Analysts")
        access_testing.add_role_member(role_id=role_id, user_id=self.member.id)
        self._rule(self.team, "warehouse_table", "editor", resource_id=table, role_id=role_id)
        self._rule(self.team, "warehouse_table", "none", resource_id=table, organization_member_id=self.membership.id)

    def test_a_member_denial_withholds_the_team_under_either_resolution(self) -> None:
        # Most-specific resolution hides the table from the member, so the floor holds for both
        # modes and a switch between them needs no push.
        self._role_editor_and_member_denied_on_one_table()
        for most_specific in (True, False):
            self.organization.uses_most_specific_access_resolution = most_specific
            self.organization.save()
            assert member_teams.member_teams(self.organization, self.member) == {}, most_specific

    def test_a_member_grant_lifts_a_default_denial(self) -> None:
        # Every resolution lets the member's own row decide, so the member reads the table.
        table = str(uuid4())
        self._rule(self.team, "warehouse_table", "none", resource_id=table)
        self._rule(self.team, "warehouse_table", "viewer", resource_id=table, organization_member_id=self.membership.id)
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "read"}

    def test_a_role_grant_does_not_lift_a_default_denial(self) -> None:
        # Without the roles entitlement the role row does not apply, so the floor keeps the denial.
        table = str(uuid4())
        role_id = access_testing.create_role(organization_id=self.organization.id, name="Analysts")
        access_testing.add_role_member(role_id=role_id, user_id=self.member.id)
        self._rule(self.team, "warehouse_table", "none", resource_id=table)
        self._rule(self.team, "warehouse_table", "viewer", resource_id=table, role_id=role_id)
        assert member_teams.member_teams(self.organization, self.member) == {}

    def test_stored_rules_cap_without_the_entitlement(self) -> None:
        # Restoring the entitlement makes the stored rules effective again with no push, so they
        # cap the grant already.
        self._rule(self.team, "warehouse_table", "none", resource_id=str(uuid4()))
        self.organization.available_product_features = []
        self.organization.save()
        assert member_teams.member_teams(self.organization, self.member) == {}

    def test_a_private_project_floor_withholds_the_team(self) -> None:
        self._rule(self.team, "project", "none", resource_id=str(self.team.id))
        self.organization.available_product_features = []
        self.organization.save()
        assert member_teams.member_teams(self.organization, self.member) == {}

    def test_an_object_default_viewer_lowers_write_to_read_in_both_modes(self) -> None:
        # Both resolutions give the member viewer on that view when no resource rule outranks it.
        for most_specific in (True, False):
            self.organization.uses_most_specific_access_resolution = most_specific
            self.organization.save()
            team = Team.objects.create(organization=self.organization, name=f"most specific {most_specific}")
            self._rule(team, "warehouse_view", "viewer", resource_id=str(uuid4()))
            assert member_teams.member_teams(self.organization, self.member)[team.id] == "read", most_specific

    def test_a_hidden_property_withholds_the_team(self) -> None:
        # The namespace holds raw property values, so a member who may not see one gets nothing.
        self._property_rule(self.team, "none", organization_member_id=self.membership.id)
        assert member_teams.member_teams(self.organization, self.member) == {}

    def test_a_read_only_property_caps_the_team_at_read(self) -> None:
        # A team grant could rewrite the raw values, which the property rule forbids.
        self._property_rule(self.team, "read")
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "read"}

    def test_a_member_property_grant_lifts_a_default_hidden_property(self) -> None:
        definition = PropertyDefinition.objects.create(team=self.team, name="email", type=2)
        for level, member in (("none", None), ("read_write", self.membership.id)):
            access_testing.create_property_access_control(
                team_id=self.team.id,
                property_definition_id=definition.id,
                access_level=level,
                organization_member_id=member,
            )
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "write"}

    def test_property_rows_naming_both_a_member_and_a_role_count(self) -> None:
        # The property resolver applies a row naming the member whatever its role, and a row
        # naming one of the member's roles whatever its member.
        role_id = access_testing.create_role(organization_id=self.organization.id, name="Analysts")
        access_testing.add_role_member(role_id=role_id, user_id=self.member.id)
        other = User.objects.create_and_join(self.organization, "other@posthog.com", "testtest")
        other_membership = OrganizationMembership.objects.get(organization=self.organization, user=other)
        for team, member_id in (
            (self.team, self.membership.id),
            (Team.objects.create(organization=self.organization, name="t2"), other_membership.id),
        ):
            definition = PropertyDefinition.objects.create(team=team, name="email", type=2)
            access_testing.create_property_access_control(
                team_id=team.id,
                property_definition_id=definition.id,
                access_level="none",
                organization_member_id=member_id,
                role_id=role_id,
            )
        assert member_teams.member_teams(self.organization, self.member) == {}

    def test_a_stored_hidden_property_caps_without_the_feature(self) -> None:
        self._property_rule(self.team, "none")
        self.organization.available_product_features = []
        self.organization.save()
        assert member_teams.member_teams(self.organization, self.member) == {}

    def test_an_organization_admin_is_not_restricted_by_property_rules(self) -> None:
        self._property_rule(self.team, "none")
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        assert member_teams.member_teams(self.organization, self.member) == {self.team.id: "write"}

    def test_an_organization_admin_is_not_restricted_by_object_rules(self) -> None:
        self._rule(self.team, "warehouse_table", "none", resource_id=str(uuid4()))
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

    def test_a_role_membership_added_or_removed_is_pushed(self) -> None:
        # The usual shape: a role membership with no organization membership on it.
        role_id = access_testing.create_role(organization_id=self.organization.id, name="Analysts")
        with self.captureOnCommitCallbacks(execute=True):
            role_membership_id = access_testing.add_role_member(role_id=role_id, user_id=self.member.id)
        self.member_push.assert_called_once_with(str(self.organization.id), str(self.member.uuid))
        self.member_push.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            access_testing.remove_role_member(
                organization_id=self.organization.id, role_membership_id=role_membership_id
            )
        self.member_push.assert_called_once_with(str(self.organization.id), str(self.member.uuid))

    def test_project_and_warehouse_rules_push_the_organization(self) -> None:
        for resource in ("project", *member_teams.RESTRICTING_RESOURCES):
            self.org_push.reset_mock()
            resource_id = None if resource in ("project", "warehouse_objects") else str(uuid4())
            with self.captureOnCommitCallbacks(execute=True):
                rule_id = self._rule(self.team, resource, "viewer", resource_id=resource_id)
            self.org_push.assert_called_once_with(str(self.organization.id))
            self.org_push.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                access_testing.delete_access_control(team_id=self.team.id, access_control_id=rule_id)
            self.org_push.assert_called_once_with(str(self.organization.id))

    def test_a_property_rule_pushes_the_organization(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            rule_id = self._property_rule(self.team, "none")
        self.org_push.assert_called_once_with(str(self.organization.id))
        self.org_push.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            access_testing.delete_property_access_control_rule(team_id=self.team.id, property_access_control_id=rule_id)
        self.org_push.assert_called_once_with(str(self.organization.id))

    def test_other_rules_push_nothing(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self._rule(self.team, "dashboard", "viewer")
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

    def test_a_project_moved_to_another_organization_pushes_both(self) -> None:
        target = Organization.objects.create(name="target")
        DuckgresServer.objects.create(organization=target, host="h2", username="u", password="p")
        with self.captureOnCommitCallbacks(execute=True):
            self.team.organization_id = target.id
            self.team.save()
        assert {call.args[0] for call in self.org_push.call_args_list} == {str(self.organization.id), str(target.id)}

    def test_a_team_save_that_keeps_the_organization_pushes_nothing(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.team.name = "renamed"
            self.team.save()
            self.team.save(update_fields=["name"])
        self.org_push.assert_not_called()

    def test_receivers_before_a_write_only_record(self) -> None:
        # Outside a transaction on_commit runs at once, so an enqueue from before the write could
        # push the old state. The receivers before the write record, and the ones after enqueue.
        target = Organization.objects.create(name="target")
        self.team.organization_id = target.id
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            signals.membership_deleting(OrganizationMembership, self.membership)
            signals.team_saving(Team, self.team)
        assert callbacks == []
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            signals.membership_deleted(OrganizationMembership, self.membership)
            signals.team_saved(Team, self.team)
        assert len(callbacks) == 3

    def test_no_push_without_a_warehouse(self) -> None:
        DuckgresServer.objects.filter(organization=self.organization).delete()
        with self.captureOnCommitCallbacks(execute=True):
            self.membership.delete()
        self.member_push.assert_not_called()

    def test_no_push_when_disabled(self) -> None:
        role_id = access_testing.create_role(organization_id=self.organization.id, name="Analysts")
        with override_settings(HOGTOWER_MEMBER_TEAMS_PUSH_ENABLED=False):
            with self.captureOnCommitCallbacks(execute=True):
                self.membership.delete()
                self._rule(self.team, "project", "none")
            # A role change does not reach the receiver, so it reads no role, when the push is off.
            with patch.object(signals, "_user_uuid") as receiver_ran:
                access_testing.add_role_member(role_id=role_id, user_id=self.user.id)
            receiver_ran.assert_not_called()
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

    def test_a_failed_publish_releases_the_claim(self) -> None:
        from products.managed_warehouse.backend.tasks import tasks  # noqa: PLC0415

        org, user = str(self.organization.id), str(self.member.uuid)
        with patch.object(
            tasks.push_warehouse_member_teams, "apply_async", side_effect=[OSError("broker"), None]
        ) as send:
            with pytest.raises(OSError):
                member_teams.enqueue_member_push(org, user)
            member_teams.enqueue_member_push(org, user)
        assert send.call_count == 2

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
