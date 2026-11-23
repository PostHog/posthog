from __future__ import annotations

from typing import Any

import pytest

from loginas import settings as loginas_settings
from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.oauth import OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey

from products.stacks.backend.facade import api
from products.stacks.backend.facade.contracts import Caller, CallerGrant, DiffSource, SetSecretInput, StartDiffInput
from products.stacks.backend.logic import credentials, crypto
from products.stacks.backend.models import StackDiff, StackSecret
from products.stacks.backend.tests.base import StackAPITestBase, resource


class TestTarget(StackAPITestBase):
    def test_a_child_environment_key_runs_against_that_environment_only(self) -> None:
        child = Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team)
        key = self.create_personal_api_key_with_scopes(["stack:read", "action:read"])
        PersonalAPIKey.objects.filter(user=self.user).update(scoped_teams=[child.id])
        self.client.logout()
        auth: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {key}"}

        parent = self.client.get(self.url("adoptable/"), {"kind": "action"}, **auth)
        # The project token resolves the route to the child, while the route's project id is the parent's.
        response = self.client.get(self.url("adoptable/"), {"kind": "action", "token": child.api_token}, **auth)

        assert parent.status_code == status.HTTP_403_FORBIDDEN
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self.engine.token_teams == [[child.id]]
        assert self.engine.credentials[0].project_id == child.id

    def test_a_child_environment_and_its_parent_never_share_a_stack(self) -> None:
        child = Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team)
        self.pushed([resource("insight", "signups")])
        self.call("put", "web/secrets/TOKEN/", {"value": "parent-value"})
        # The project route resolves a write to the project's main environment, so the child's writes go through
        # the facade as a route resolved to the child would call it.
        caller = Caller(
            user_id=self.user.id,
            grant=CallerGrant(type="session", id=""),
            target_team_id=child.id,
            organization_id=str(self.organization.id),
            held_scopes=None,
        )
        api.set_secret(
            SetSecretInput(team_id=child.id, stack_name="web", name="TOKEN", value="child-value", caller=caller)
        )
        with self.captureOnCommitCallbacks(using="stacks_db_writer", execute=True):
            diff = api.start_diff(
                StartDiffInput(
                    team_id=child.id,
                    stack_name="web",
                    description={"version": 1, "resources": [resource("insight", "churn")]},
                    source=DiffSource(repository="org/web", branch="main", commit="abc123"),
                    caller=caller,
                ),
                scopes=["insight:read"],
            )
        self.run_diff(str(diff.id))

        key = self.create_personal_api_key_with_scopes(["stack:read"])
        self.client.logout()
        auth: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {key}"}
        child_bindings = self.client.get(self.url("web/bindings/"), {"token": child.api_token}, **auth)
        parent_bindings = self.client.get(self.url("web/bindings/"), **auth)

        # The child's diff starts from its own empty record: one create, and no removal of the parent's insight.
        summary = (StackDiff.all_teams.using("stacks_db_writer").get(id=diff.id).diff or {})["summary"]
        assert (summary["create"], summary["remove"]) == (1, 0)
        assert child_bindings.json()["results"] == []
        assert [binding["key"] for binding in parent_bindings.json()["results"]] == ["signups"]
        secrets = {
            secret.stack.target_team_id: crypto.decrypt(bytes(secret.encrypted_value)).decode()
            for secret in StackSecret.all_teams.using("stacks_db_writer").select_related("stack")
        }
        assert secrets == {self.team.id: "parent-value", child.id: "child-value"}


class TestReaders(StackAPITestBase):
    def test_reading_a_diff_needs_its_read_scopes(self) -> None:
        diff = self.ready_diff([resource("insight", "signups")])
        key = self.create_personal_api_key_with_scopes(["stack:read"])
        self.client.logout()

        response = self.client.get(self.url(f"web/diffs/{diff['id']}/"), HTTP_AUTHORIZATION=f"Bearer {key}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["extra"]["required_scopes"] == ["insight:read"]

    @parameterized.expand(
        [
            ("member", OrganizationMembership.Level.MEMBER, None),
            ("admin", OrganizationMembership.Level.ADMIN, "signups"),
        ]
    )
    def test_field_values_are_shown_to_the_creator_and_admins_only(
        self, _name: str, level: OrganizationMembership.Level, seen: str | None
    ) -> None:
        diff = self.ready_diff([resource("insight", "signups")])
        assert diff["diff"]["changes"][0]["fields"][0]["after"] == "signups"
        reader = User.objects.create_and_join(self.organization, "reader@example.com", None, level=level)
        self.client.force_login(reader)

        shown = self.get_diff(diff["id"])

        assert shown["diff"]["changes"][0]["fields"][0]["after"] == seen
        assert shown["diff"]["changes"][0]["action"] == "create"

    def test_adoptable_entities_come_from_the_kind_api_with_the_callers_read_scope(self) -> None:
        managed = self.engine.remote.add("action", {"name": "Managed"})
        free = self.engine.remote.add("action", {"name": "Free"})
        self.call("post", "web/adopt/", {"resources": [{"kind": "action", "key": "managed", "entity_id": managed}]})

        response = self.client.get(self.url("adoptable/"), {"kind": "action"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [item["entity_id"] for item in response.json()["results"]] == [free]
        assert self.engine.token_scopes[-1] == "action:read"

    def test_another_team_cannot_read_or_push_a_stack(self) -> None:
        diff = self.ready_diff([resource("insight", "signups")])
        other_team = Team.objects.create(organization=self.organization, name="Other")

        assert (
            self.client.get(self.url(f"web/diffs/{diff['id']}/", other_team)).status_code == status.HTTP_404_NOT_FOUND
        )
        assert (
            self.call("post", f"web/diffs/{diff['id']}/push/", team=other_team).status_code == status.HTTP_404_NOT_FOUND
        )

        outsider = User.objects.create_and_join(
            Organization.objects.create(name="Outsider"), "outsider@example.com", None
        )
        self.client.force_login(outsider)
        assert self.client.get(self.url(f"web/diffs/{diff['id']}/")).status_code == status.HTTP_403_FORBIDDEN
        assert self.dispatcher.pushes == []


class TestRunAuthority(StackAPITestBase):
    def test_the_worker_mints_the_admitted_scopes_and_refuses_a_revoked_key(self) -> None:
        key = self.create_personal_api_key_with_scopes(["stack:read", "insight:read"])
        self.client.logout()
        response = self.start_diff([resource("insight", "signups")], HTTP_AUTHORIZATION=f"Bearer {key}")
        assert StackDiff.all_teams.get(id=response.json()["id"]).run_scopes == ["insight:read"]
        PersonalAPIKey.objects.filter(user=self.user).delete()

        self.run_diff(response.json()["id"])

        self.client.force_login(self.user)
        diff = self.get_diff(response.json()["id"])
        assert (diff["status"], diff["diff"]["errors"][0]["code"]) == ("failed", "caller_unavailable")
        assert self.engine.credentials == []

    def test_a_push_from_an_impersonated_session_is_refused(self) -> None:
        diff = self.ready_diff([resource("insight", "signups")])
        session = self.client.session
        session[loginas_settings.USER_SESSION_FLAG] = "1"
        session.save()

        response = self.push(diff["id"])

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == "impersonated_push"

    def test_a_removal_of_the_last_entity_of_a_kind_still_needs_its_scopes(self) -> None:
        self.pushed([resource("insight", "signups")])
        key = self.create_personal_api_key_with_scopes(["stack:read"])
        self.client.logout()

        response = self.start_diff([], HTTP_AUTHORIZATION=f"Bearer {key}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["extra"]["required_scopes"] == ["insight:read"]

    def test_an_unknown_kind_is_refused(self) -> None:
        response = self.start_diff([resource("spaceship", "one")])

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "kind_unsupported"
        assert not StackDiff.all_teams.exists()

    def test_a_dependency_the_push_only_reads_gets_only_read(self) -> None:
        diff = self.ready_diff([resource("alert", "spike")])

        self.push(diff["id"])

        assert StackDiff.all_teams.get(id=diff["id"]).push_scopes == ["alert:read", "alert:write", "insight:read"]

    @parameterized.expand(
        [
            ("adopt", ["stack:write"], "adopt", status.HTTP_403_FORBIDDEN),
            ("adopt", ["stack:write", "action:read", "action:write"], "adopt", status.HTTP_200_OK),
            ("detach", ["stack:write"], "detach", status.HTTP_403_FORBIDDEN),
            ("detach", ["stack:write", "action:read", "action:write"], "detach", status.HTTP_200_OK),
        ]
    )
    def test_binding_changes_need_the_kinds_write_scope(
        self, _name: str, scopes: list, call: str, expected: int
    ) -> None:
        existing = self.engine.remote.add("action", {"name": "Signup"})
        if call == "detach":
            self.call("post", "web/adopt/", {"resources": [{"kind": "action", "key": "signup", "entity_id": existing}]})
            binding_id = self.bindings()[0]["id"]
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        auth: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {key}"}

        if call == "adopt":
            body = {"resources": [{"kind": "action", "key": "signup", "entity_id": existing}]}
            response = self.call("post", "web/adopt/", body, **auth)
        else:
            response = self.call("post", f"web/bindings/{binding_id}/detach/", **auth)

        assert response.status_code == expected, response.json()

    @parameterized.expand(
        [
            ("diff_without_kind_scope", ["stack:read"], "diff", status.HTTP_403_FORBIDDEN),
            ("diff", ["stack:read", "insight:read"], "diff", status.HTTP_202_ACCEPTED),
            ("push_with_read_only", ["stack:read", "insight:write"], "push", status.HTTP_403_FORBIDDEN),
            ("push_without_kind_scope", ["stack:write", "insight:read"], "push", status.HTTP_403_FORBIDDEN),
            ("push", ["stack:write", "insight:read", "insight:write"], "push", status.HTTP_202_ACCEPTED),
        ]
    )
    def test_personal_api_key_scopes(self, _name: str, scopes: list[str], call: str, expected: int) -> None:
        diff = self.ready_diff([resource("insight", "signups")])
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        auth: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {key}"}

        if call == "diff":
            response = self.start_diff([resource("insight", "signups")], **auth)
        else:
            response = self.call("post", f"web/diffs/{diff['id']}/push/", **auth)

        assert response.status_code == expected, response.json()


class TestStacksApplication(StackAPITestBase):
    def test_a_row_that_is_not_first_party_never_mints(self) -> None:
        OAuthApplication.objects.create(
            client_id=credentials.STACKS_OAUTH_CLIENT_ID,
            name="Lookalike",
            client_secret="x" * 48,
            client_type="confidential",
            authorization_grant_type="authorization-code",
            redirect_uris=credentials.STACKS_OAUTH_REDIRECT_URI,
            algorithm="RS256",
            is_first_party=False,
            scopes=["insight:read"],
        )
        diff = self.start_diff([resource("insight", "signups")]).json()

        self.run_diff(diff["id"])

        assert self.get_diff(diff["id"])["diff"]["errors"][0]["code"] == "caller_unavailable"
        assert self.engine.credentials == []

    def test_a_scope_outside_the_ceiling_is_never_minted(self) -> None:
        with pytest.raises(credentials.CallerUnavailable):
            credentials.mint(user=self.user, target_team_id=self.team.id, scopes=["person:write"])

    def test_provisioning_twice_keeps_one_row(self) -> None:
        first = credentials.provision_stacks_oauth_app()
        second = credentials.provision_stacks_oauth_app()

        assert first.id == second.id
        assert second.scopes and second.is_first_party
        assert OAuthApplication.objects.filter(client_id=credentials.STACKS_OAUTH_CLIENT_ID).count() == 1
