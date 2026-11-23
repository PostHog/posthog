from __future__ import annotations

from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from rest_framework import status

from posthog.models import OrganizationMembership, Team

from products.feature_flags.backend.models import FeatureFlag
from products.stacks.backend import engine_adapter
from products.stacks.backend.logic import credentials, managed
from products.stacks.backend.models import Stack, StackBinding
from products.stacks.backend.tests.base import StackAPITestBase, resource


class TestScopeCeiling(BaseTest):
    def test_the_application_ceiling_covers_every_mapped_kind(self) -> None:
        app = credentials.provision_stacks_oauth_app()

        for kind in engine_adapter.mapped_kinds():
            assert set(engine_adapter.kind_scopes(kind)["write"]) <= set(app.scopes), kind

    def test_a_scope_a_mapping_gains_reaches_the_ceiling(self) -> None:
        declared = engine_adapter.kind_scopes

        def with_new_scope(kind: str) -> dict[str, list[str]]:
            scopes = declared(kind)
            return {"read": scopes["read"], "write": [*scopes["write"], "inbox:read"]} if kind == "insight" else scopes

        with patch.object(engine_adapter, "kind_scopes", with_new_scope):
            app = credentials.provision_stacks_oauth_app()

        assert "inbox:read" in app.scopes


class TestContextPages(StackAPITestBase):
    def setUp(self) -> None:
        super().setUp()
        OrganizationMembership.objects.filter(user=self.user).update(level=OrganizationMembership.Level.ADMIN)

    def test_turning_context_pages_off_stops_a_queued_push(self) -> None:
        assert self.call("post", "web/context_pages/", {"enabled": True}).status_code == status.HTTP_200_OK
        diff = self.ready_diff([resource("context_page", "handbook/metrics")])
        assert self.push(diff["id"]).status_code == status.HTTP_202_ACCEPTED

        assert self.call("post", "web/context_pages/", {"enabled": False}).status_code == status.HTTP_200_OK
        self.run_push(diff["id"])

        assert self.get_diff(diff["id"])["push_status"] == "failed"
        assert self.engine.remote.of("context_page") == {}

    def test_a_stack_manages_context_pages_only_after_an_organization_admin_opts_in(self) -> None:
        page = resource("context_page", "handbook/metrics")

        refused = self.start_diff([page])
        assert refused.status_code == status.HTTP_400_BAD_REQUEST
        assert refused.json()["code"] == "context_pages_not_enabled"

        OrganizationMembership.objects.filter(user=self.user).update(level=OrganizationMembership.Level.MEMBER)
        member = self.call("post", "web/context_pages/", {"enabled": True})
        assert member.status_code == status.HTTP_403_FORBIDDEN
        OrganizationMembership.objects.filter(user=self.user).update(level=OrganizationMembership.Level.ADMIN)
        assert self.call("post", "web/context_pages/", {"enabled": True}).json()["context_pages_enabled"] is True

        diff = self.ready_diff([page])
        assert diff["status"] == "ready"
        assert self.engine.token_scopes[-1] == "organization:read"

    def test_one_page_is_claimed_once_across_the_organizations_projects(self) -> None:
        other = Team.objects.create(organization=self.organization, name="Other project")
        self.engine.remote.add("context_page", {"name": "Metrics"}, entity_id="handbook/metrics")
        body = {"resources": [{"kind": "context_page", "key": "metrics", "entity_id": "handbook/metrics"}]}

        refused = self.call("post", "web/adopt/", body)
        assert refused.json()["code"] == "context_pages_not_enabled"
        for team in (self.team, other):
            assert self.call("post", "web/context_pages/", {"enabled": True}, team=team).status_code == 200

        first = self.call("post", "web/adopt/", body)
        second = self.call("post", "web/adopt/", body, team=other)

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()["code"] == "claimed_by_other_stack"


class TestDiffShape(StackAPITestBase):
    def test_drift_says_when_an_entity_was_deleted_outside_code(self) -> None:
        self.engine.drift = [{"kind": "insight", "key": "signups", "fields": [], "deleted": True}]

        diff = self.ready_diff([resource("insight", "signups")])

        assert diff["diff"]["drift"] == [{"kind": "insight", "key": "signups", "deleted": True, "fields": []}]

    def test_a_natural_key_longer_than_a_slug_is_kept_whole(self) -> None:
        key = "checkout-" + "x" * 300
        flag = {**resource("flag", key, key=key), "source": {"file": ".ph/flags.ts", "export": "longFlag"}}

        self.pushed([flag])

        assert StackBinding.all_teams.using("stacks_db_writer").get().key == key


class TestManagedKinds(StackAPITestBase):
    def test_managed_kinds_name_the_stack_and_repository_and_are_cached(self) -> None:
        cache.clear()
        self.pushed([resource("insight", "a"), resource("insight", "b")])

        first = self.client.get(self.url("managed_kinds/"))
        with self.assertNumQueries(0, using="stacks_db_writer"):
            second = self.client.get(self.url("managed_kinds/"))

        expected = [
            {
                "kind": "insight",
                "stack_name": "web",
                "repository": "org/web",
                "definitions": 2,
                "redirect_creates": False,
            }
        ]
        assert first.status_code == status.HTTP_200_OK, first.json()
        assert first.json()["results"] == second.json()["results"] == expected

    def test_natural_key_kinds_redirect_creates(self) -> None:
        self.pushed([resource("flag", "beta", key="beta")])

        [row] = self.client.get(self.url("managed_kinds/")).json()["results"]

        assert (row["kind"], row["redirect_creates"]) == ("flag", True)


class TestNestedOwnedFields(StackAPITestBase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.flag = FeatureFlag.objects.create(
            team=self.team,
            key="beta",
            name="Beta",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {"true": '"a"'}},
        )
        stack = Stack.all_teams.using("stacks_db_writer").create(
            team_id=self.team.id,
            target_team_id=self.team.id,
            name="web",
            repository="org/web",
            organization_id=str(self.organization.id),
        )
        StackBinding.all_teams.using("stacks_db_writer").create(
            team_id=self.team.id,
            stack=stack,
            kind="flag",
            key="beta",
            entity_id=str(self.flag.id),
            claim_scope=f"team:{self.team.id}",
            owned_fields=["filters.groups", "filters.payloads"],
        )
        managed.restore_markers()

    def patch_filters(self, filters: dict[str, Any]):
        return self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{self.flag.id}/", {"filters": filters}, format="json"
        )

    def test_only_the_owned_nested_path_is_locked(self) -> None:
        groups = [{"properties": [], "rollout_percentage": 100}]
        payload = self.patch_filters({"groups": groups, "payloads": {"true": '"b"'}})
        # 100.0 is the 100 already stored.
        same = self.patch_filters(
            {"groups": [{"properties": [], "rollout_percentage": 100.0}], "payloads": {"true": '"a"'}}
        )
        dropped = self.patch_filters({"groups": groups})

        assert same.status_code == status.HTTP_200_OK, same.json()
        assert payload.status_code == status.HTTP_409_CONFLICT
        assert payload.json()["extra"]["fields"] == ["filters.payloads"]
        # Sending `filters` without `payloads` replaces the parent and drops the owned child.
        assert dropped.status_code == status.HTTP_409_CONFLICT
        assert "filters.payloads" in dropped.json()["extra"]["fields"]
