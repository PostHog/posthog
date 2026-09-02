from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataDestination,
    ExternalDataSchemaDestination,
    ExternalDataSourceDestination,
    get_or_create_warehouse_destination,
    resolve_destinations,
)
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestResolveDestinations(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src",
            connection_id="conn",
            status="Running",
            source_type=ExternalDataSourceType.STRIPE,
        )
        self.schema = ExternalDataSchema.objects.create(team=self.team, source=self.source, name="charges")

    def _destination(
        self, name: str, type_: str = str(ExternalDataDestination.Type.REDSHIFT)
    ) -> ExternalDataDestination:
        return ExternalDataDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, type=type_, name=name
        )

    def test_no_links_resolves_to_the_warehouse(self) -> None:
        resolved = resolve_destinations(self.schema)

        assert [d.type for d in resolved] == [ExternalDataDestination.Type.POSTHOG_WAREHOUSE]

    def test_source_links_apply_when_the_schema_has_no_override(self) -> None:
        redshift = self._destination("redshift")
        ExternalDataSourceDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, source=self.source, destination=redshift
        )

        assert [d.id for d in resolve_destinations(self.schema)] == [redshift.id]

    def test_schema_links_override_source_links(self) -> None:
        source_level = self._destination("source-level")
        schema_level = self._destination("schema-level", ExternalDataDestination.Type.SNOWFLAKE)
        ExternalDataSourceDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, source=self.source, destination=source_level
        )
        ExternalDataSchemaDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, schema=self.schema, destination=schema_level
        )

        assert [d.id for d in resolve_destinations(self.schema)] == [schema_level.id]

    def test_a_disabled_schema_link_does_not_fall_back_to_the_source(self) -> None:
        source_level = self._destination("source-level")
        schema_level = self._destination("schema-level", ExternalDataDestination.Type.SNOWFLAKE)
        ExternalDataSourceDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, source=self.source, destination=source_level
        )
        ExternalDataSchemaDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, schema=self.schema, destination=schema_level, enabled=False
        )

        assert resolve_destinations(self.schema) == []

    def test_deleted_destinations_are_excluded(self) -> None:
        live = self._destination("live")
        gone = self._destination("gone", ExternalDataDestination.Type.SNOWFLAKE)
        gone.deleted = True
        gone.save()
        for destination in (live, gone):
            ExternalDataSourceDestination.objects.for_team(self.team.pk).create(
                team_id=self.team.pk, source=self.source, destination=destination
            )

        assert [d.id for d in resolve_destinations(self.schema)] == [live.id]


class TestGetOrCreateWarehouseDestination(BaseTest):
    def test_repeated_calls_return_the_same_row(self) -> None:
        first = get_or_create_warehouse_destination(self.team.pk)
        second = get_or_create_warehouse_destination(self.team.pk)

        assert first.id == second.id
        assert ExternalDataDestination.objects.for_team(self.team.pk).count() == 1

    def test_each_team_gets_its_own_row(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")

        mine = get_or_create_warehouse_destination(self.team.pk)
        theirs = get_or_create_warehouse_destination(other_team.pk)

        assert mine.id != theirs.id
