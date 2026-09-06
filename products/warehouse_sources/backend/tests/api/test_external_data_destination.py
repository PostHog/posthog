from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status
from rest_framework.exceptions import PermissionDenied

from posthog.models.integration import Integration

from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataDestination,
    ExternalDataSchemaDestination,
    ExternalDataSourceDestination,
)
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.presentation.views.external_data_destination import (
    ExternalDataDestinationViewSet,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class DestinationAPITestBase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.pk}/external_data_destinations"
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src",
            connection_id="conn",
            status="Running",
            source_type=ExternalDataSourceType.STRIPE,
        )
        self.schema = ExternalDataSchema.objects.create(team=self.team, source=self.source, name="charges")

    def _integration(self, kind: str = Integration.IntegrationKind.POSTGRESQL) -> Integration:
        self._integration_seq = getattr(self, "_integration_seq", 0) + 1
        return Integration.objects.create(
            team=self.team, kind=kind, integration_id=f"{kind}-{self._integration_seq}", config={}
        )

    def _create_destination(self, **overrides) -> ExternalDataDestination:
        payload = {
            "type": ExternalDataDestination.Type.POSTGRES,
            "name": "analytics postgres",
            "integration": self._integration().pk,
            **overrides,
        }
        response = self.client.post(self.base, payload)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return ExternalDataDestination.objects.for_team(self.team.pk).get(id=response.json()["id"])


class TestExternalDataDestinationAPI(DestinationAPITestBase):
    def test_create_and_list(self) -> None:
        destination = self._create_destination()

        listing = self.client.get(self.base).json()

        assert [d["id"] for d in listing["results"]] == [str(destination.id)]
        assert listing["results"][0]["is_posthog_warehouse"] is False

    def test_a_destination_needs_an_integration(self) -> None:
        response = self.client.post(self.base, {"type": ExternalDataDestination.Type.POSTGRES, "name": "no creds"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "integration" in response.json()["attr"]

    def test_the_integration_must_match_the_destination_type(self) -> None:
        # Postgres needs a postgresql integration, not a Snowflake one.
        snowflake_integration = self._integration(Integration.IntegrationKind.SNOWFLAKE)

        response = self.client.post(
            self.base,
            {
                "type": ExternalDataDestination.Type.POSTGRES,
                "name": "mismatched",
                "integration": snowflake_integration.pk,
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "integration" in response.json()["attr"]

    def test_the_posthog_warehouse_is_not_user_managed(self) -> None:
        response = self.client.post(self.base, {"type": ExternalDataDestination.Type.POSTHOG_WAREHOUSE, "name": "mine"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_the_connection_cannot_be_changed(self) -> None:
        # Repointing at another server strands everything already synced there, so a second
        # destination is the supported route rather than editing this one.
        destination = self._create_destination()
        other = self._integration()

        response = self.client.patch(f"{self.base}/{destination.id}", {"integration": other.pk})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "integration" in response.json()["attr"]

    def test_the_target_database_and_schema_cannot_be_changed(self) -> None:
        destination = self._create_destination()

        for field in ("database", "schema"):
            response = self.client.patch(f"{self.base}/{destination.id}", {"config": {field: "somewhere_else"}})

            assert response.status_code == status.HTTP_400_BAD_REQUEST, field
            assert "config" in response.json()["attr"], field

    def test_the_name_can_still_be_changed(self) -> None:
        destination = self._create_destination()

        response = self.client.patch(f"{self.base}/{destination.id}", {"name": "renamed"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        destination.refresh_from_db()
        assert destination.name == "renamed"

    def test_resending_the_same_target_is_not_a_change(self) -> None:
        # A form that posts every field back must not be rejected for the fields it left alone.
        destination = self._create_destination()

        response = self.client.patch(
            f"{self.base}/{destination.id}",
            {"name": "renamed", "integration": destination.integration_id, "config": destination.config},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_delete_detaches_everything_that_synced_to_it(self) -> None:
        destination = self._create_destination()
        ExternalDataSourceDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, source=self.source, destination=destination
        )
        ExternalDataSchemaDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, schema=self.schema, destination=destination
        )

        response = self.client.delete(f"{self.base}/{destination.id}")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        destination.refresh_from_db()
        assert destination.deleted is True
        assert ExternalDataSourceDestination.objects.for_team(self.team.pk).count() == 0
        assert ExternalDataSchemaDestination.objects.for_team(self.team.pk).count() == 0

    def test_another_teams_destinations_are_not_visible(self) -> None:
        self._create_destination()
        other_team = self.create_team_with_organization(self.organization)

        listing = self.client.get(f"/api/projects/{other_team.pk}/external_data_destinations").json()

        assert listing["results"] == []

    def test_delete_requires_editor_on_every_wired_table(self) -> None:
        destination = self._create_destination()
        ExternalDataSourceDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, source=self.source, destination=destination
        )

        with patch.object(ExternalDataDestinationViewSet, "_assert_can_mutate", side_effect=PermissionDenied("nope")):
            response = self.client.delete(f"{self.base}/{destination.id}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        destination.refresh_from_db()
        assert destination.deleted is False
        assert ExternalDataSourceDestination.objects.for_team(self.team.pk).count() == 1

    def test_update_requires_editor_on_every_wired_table(self) -> None:
        destination = self._create_destination()
        ExternalDataSchemaDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, schema=self.schema, destination=destination
        )

        with patch.object(ExternalDataDestinationViewSet, "_assert_can_mutate", side_effect=PermissionDenied("nope")):
            response = self.client.patch(f"{self.base}/{destination.id}", {"name": "renamed"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        destination.refresh_from_db()
        assert destination.name == "analytics postgres"


class TestDestinationLinkEndpoints(DestinationAPITestBase):
    def setUp(self) -> None:
        super().setUp()
        self.destination = self._create_destination()
        self.source_url = f"/api/projects/{self.team.pk}/external_data_sources/{self.source.id}/destinations"
        self.schema_url = f"/api/projects/{self.team.pk}/external_data_schemas/{self.schema.id}/destinations"

    def test_setting_source_destinations_round_trips(self) -> None:
        patch = self.client.patch(self.source_url, {"destination_ids": [str(self.destination.id)]})

        assert patch.status_code == status.HTTP_200_OK, patch.json()
        assert self.client.get(self.source_url).json()["destination_ids"] == [str(self.destination.id)]

    def test_setting_source_destinations_replaces_the_previous_set(self) -> None:
        other = self._create_destination(name="second", integration=self._integration().pk)
        self.client.patch(self.source_url, {"destination_ids": [str(self.destination.id)]})

        self.client.patch(self.source_url, {"destination_ids": [str(other.id)]})

        assert self.client.get(self.source_url).json()["destination_ids"] == [str(other.id)]

    def test_an_unknown_destination_is_rejected(self) -> None:
        response = self.client.patch(self.source_url, {"destination_ids": ["00000000-0000-0000-0000-000000000000"]})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_a_table_inherits_its_source_until_it_is_overridden(self) -> None:
        self.client.patch(self.source_url, {"destination_ids": [str(self.destination.id)]})

        body = self.client.get(self.schema_url).json()

        assert body["inherits_from_source"] is True
        assert body["destination_ids"] is None
        assert body["effective_destination_ids"] == [str(self.destination.id)]

    def test_overriding_a_table_stops_it_following_the_source(self) -> None:
        other = self._create_destination(name="table only", integration=self._integration().pk)
        self.client.patch(self.source_url, {"destination_ids": [str(self.destination.id)]})

        self.client.patch(self.schema_url, {"destination_ids": [str(other.id)]})

        body = self.client.get(self.schema_url).json()
        assert body["inherits_from_source"] is False
        assert body["effective_destination_ids"] == [str(other.id)]

    def test_clearing_the_override_restores_inheritance(self) -> None:
        other = self._create_destination(name="table only", integration=self._integration().pk)
        self.client.patch(self.source_url, {"destination_ids": [str(self.destination.id)]})
        self.client.patch(self.schema_url, {"destination_ids": [str(other.id)]})

        self.client.patch(self.schema_url, {"destination_ids": None})

        body = self.client.get(self.schema_url).json()
        assert body["inherits_from_source"] is True
        assert body["effective_destination_ids"] == [str(self.destination.id)]

    def test_an_empty_set_is_rejected_rather_than_silently_inheriting(self) -> None:
        # With no rows left there is nothing to tell "override with nothing" apart from "no
        # override", so accepting it would quietly fall back to the source's destinations.
        self.client.patch(self.source_url, {"destination_ids": [str(self.destination.id)]})

        response = self.client.patch(self.schema_url, {"destination_ids": []})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = self.client.get(self.schema_url).json()
        assert body["effective_destination_ids"] == [str(self.destination.id)]

    def test_a_source_cannot_be_left_with_no_destinations(self) -> None:
        response = self.client.patch(self.source_url, {"destination_ids": []})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_a_rejected_override_leaves_the_previous_one_in_place(self) -> None:
        # There are no ATOMIC_REQUESTS, so clearing the override before validating the
        # replacement would commit the clear and re-route the table to its source.
        other = self._create_destination(name="table only", integration=self._integration().pk)
        self.client.patch(self.source_url, {"destination_ids": [str(self.destination.id)]})
        self.client.patch(self.schema_url, {"destination_ids": [str(other.id)]})

        response = self.client.patch(self.schema_url, {"destination_ids": ["00000000-0000-0000-0000-000000000000"]})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = self.client.get(self.schema_url).json()
        assert body["inherits_from_source"] is False
        assert body["destination_ids"] == [str(other.id)]
