"""The write lock on the product routes that write without loading one object through `get_object`.

Each test goes through the real route and shows both sides: a managed entity or an owned field is refused, and
an unmanaged entity or an unowned field still changes. A route that stops calling the check fails here.
"""

from __future__ import annotations

from typing import Any

from django.core.cache import cache

from rest_framework import status

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile, Text
from products.event_definitions.backend.models import EventDefinition, EventSchema, SchemaPropertyGroup
from products.feature_flags.backend.models import FeatureFlag
from products.stacks.backend.logic import managed
from products.stacks.backend.models import Stack, StackBinding
from products.stacks.backend.tests.base import StackAPITestBase


class ManagedRouteTest(StackAPITestBase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.stack = Stack.all_teams.using("stacks_db_writer").create(
            team_id=self.team.id,
            target_team_id=self.team.id,
            name="web",
            repository="org/web",
            organization_id=str(self.organization.id),
        )

    def bind(self, kind: str, entity_id: Any, owned: list[str], key: str | None = None) -> None:
        StackBinding.all_teams.using("stacks_db_writer").create(
            team_id=self.team.id,
            stack=self.stack,
            kind=kind,
            key=key or str(entity_id),
            entity_id=str(entity_id),
            claim_scope=f"team:{self.team.id}",
            owned_fields=owned,
        )
        managed.restore_markers()

    def api(self, path: str) -> str:
        return f"/api/projects/{self.team.id}/{path}"

    def post(self, path: str, body: dict[str, Any]):
        return self.client.post(self.api(path), body, format="json")

    def insight(self, name: str) -> int:
        # Through the API: the insight model is not part of the product's public interface.
        query = {"kind": "DataVisualizationNode", "source": {"kind": "HogQLQuery", "query": "select 1"}}
        response = self.post("insights/", {"name": name, "query": query})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()["id"]


class TestEventDefinitionRoutes(ManagedRouteTest):
    def setUp(self) -> None:
        super().setUp()
        self.managed = EventDefinition.objects.create(team=self.team, name="checkout_completed")
        self.free = EventDefinition.objects.create(team=self.team, name="page_viewed")
        # The engine knows an event by its name.
        self.bind("event", "checkout_completed", ["description", "tags", "property_groups"])

    def test_the_detail_route_that_loads_its_own_object_is_locked(self) -> None:
        refused = self.client.patch(self.api(f"event_definitions/{self.managed.id}/"), {"description": "UI"})
        allowed = self.client.patch(self.api(f"event_definitions/{self.free.id}/"), {"description": "UI"})

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.json()
        assert refused.json()["extra"]["fields"] == ["description"]
        assert allowed.status_code == status.HTTP_200_OK, allowed.json()

    def test_bulk_tags_skip_a_managed_event(self) -> None:
        response = self.post(
            "event_definitions/bulk_update_tags/",
            {"ids": [str(self.managed.id), str(self.free.id)], "action": "add", "tags": ["ui"]},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [item["id"] for item in response.json()["updated"]] == [str(self.free.id)]
        assert response.json()["skipped"][0]["id"] == str(self.managed.id)
        assert "managed in code" in response.json()["skipped"][0]["reason"]

    def test_bulk_verification_skips_a_managed_event(self) -> None:
        StackBinding.all_teams.using("stacks_db_writer").update(owned_fields=["verified"])
        cache.clear()

        response = self.post(
            "event_definitions/bulk_update_verified/",
            {"ids": [str(self.managed.id), str(self.free.id)], "verified": True},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [item["id"] for item in response.json()["updated"]] == [str(self.free.id)]
        assert response.json()["skipped"][0]["id"] == str(self.managed.id)

    def test_a_property_group_link_on_a_managed_event_is_refused(self) -> None:
        group = SchemaPropertyGroup.objects.create(team=self.team, project=self.project, name="checkout")

        refused = self.post(
            "event_schemas/", {"event_definition": str(self.managed.id), "property_group_id": str(group.id)}
        )
        allowed = self.post(
            "event_schemas/", {"event_definition": str(self.free.id), "property_group_id": str(group.id)}
        )

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.json()
        assert allowed.status_code == status.HTTP_201_CREATED, allowed.json()
        assert list(EventSchema.objects.values_list("event_definition_id", flat=True)) == [self.free.id]


class TestFeatureFlagRoutes(ManagedRouteTest):
    def test_bulk_delete_skips_a_managed_flag(self) -> None:
        managed_flag = FeatureFlag.objects.create(team=self.team, key="beta", created_by=self.user)
        free = FeatureFlag.objects.create(team=self.team, key="free", created_by=self.user)
        # No owned field: a managed entity is never deleted outside its stack.
        self.bind("flag", managed_flag.id, [])

        response = self.post("feature_flags/bulk_delete/", {"ids": [managed_flag.id, free.id]})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [error["id"] for error in response.json()["errors"]] == [managed_flag.id]
        assert [item["id"] for item in response.json()["deleted"]] == [free.id]
        managed_flag.refresh_from_db()
        assert managed_flag.deleted is False


class TestInsightAndDashboardRoutes(ManagedRouteTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, name="Managed", created_by=self.user)
        self.free_dashboard = Dashboard.objects.create(team=self.team, name="Free", created_by=self.user)

    def test_insight_bulk_delete_skips_a_managed_insight(self) -> None:
        managed_insight, free = self.insight("Managed"), self.insight("Free")
        self.bind("insight", managed_insight, ["name"])

        response = self.post("insights/bulk_delete/", {"ids": [managed_insight, free]})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [item["id"] for item in response.json()["deleted"]] == [free]
        assert [item["id"] for item in response.json()["skipped"]] == [managed_insight]

    def test_dashboard_bulk_delete_skips_a_managed_dashboard(self) -> None:
        self.bind("dashboard", self.dashboard.id, ["name"])

        response = self.post("dashboards/bulk_delete/", {"ids": [self.dashboard.id, self.free_dashboard.id]})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["deleted"] == [self.free_dashboard.id]
        assert [item["id"] for item in response.json()["skipped"]] == [self.dashboard.id]

    def _two_text_tiles(self, dashboard: Dashboard) -> list[int]:
        return [
            DashboardTile.objects.create(dashboard=dashboard, text=Text.objects.create(team=self.team, body=body)).id
            for body in ("one", "two")
        ]

    def test_tile_actions_are_refused_only_when_code_owns_the_tiles(self) -> None:
        self.bind("dashboard", self.dashboard.id, ["tiles"])
        self.bind("dashboard", self.free_dashboard.id, ["name"])
        owned_tiles = self._two_text_tiles(self.dashboard)
        free_tiles = self._two_text_tiles(self.free_dashboard)

        refused = self.post(f"dashboards/{self.dashboard.id}/reorder_tiles/", {"tile_order": owned_tiles[::-1]})
        allowed = self.post(f"dashboards/{self.free_dashboard.id}/reorder_tiles/", {"tile_order": free_tiles[::-1]})

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.json()
        assert refused.json()["extra"]["fields"] == ["tiles"]
        assert allowed.status_code == status.HTTP_200_OK, allowed.json()

    def test_an_insight_edit_cannot_put_it_on_a_dashboard_whose_tiles_code_owns(self) -> None:
        self.bind("dashboard", self.dashboard.id, ["tiles"])
        insight = self.insight("Free")

        refused = self.client.patch(self.api(f"insights/{insight}/"), {"dashboards": [self.dashboard.id]})
        allowed = self.client.patch(self.api(f"insights/{insight}/"), {"dashboards": [self.free_dashboard.id]})

        assert refused.status_code == status.HTTP_409_CONFLICT, refused.json()
        assert allowed.status_code == status.HTTP_200_OK, allowed.json()
        assert list(DashboardTile.objects.filter(insight_id=insight).values_list("dashboard_id", flat=True)) == [
            self.free_dashboard.id
        ]
