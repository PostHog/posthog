from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

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
from products.warehouse_sources.backend.temporal.data_imports.destinations.enablement import (
    NoActiveDestinationsError,
    destination_ids_for_run,
    external_destination_ids_for,
)
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
        # An empty id list means "the PostHog warehouse only", which this table never picked.
        with self.assertRaises(NoActiveDestinationsError):
            destination_ids_for_run(self.schema)

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


class TestBackfillWarehouseSourceDestinations(BaseTest):
    def _source(self, source_id: str, team: Team | None = None) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=team or self.team,
            source_id=source_id,
            connection_id=f"conn-{source_id}",
            status="Running",
            source_type=ExternalDataSourceType.STRIPE,
        )

    @parameterized.expand(
        [
            ("new_destination_first_run", 1, False),
            ("new_destination_second_run", 2, False),
            ("existing_destination_first_run", 1, True),
            ("existing_destination_second_run", 2, True),
        ]
    )
    def test_a_source_without_links_gains_one_for_the_warehouse(
        self, _case: str, runs: int, warehouse_exists: bool
    ) -> None:
        source = self._source("src")
        existing_destination = get_or_create_warehouse_destination(self.team.pk) if warehouse_exists else None

        for _ in range(runs):
            call_command("backfill_warehouse_source_destinations", live_run=True)

        links = list(ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source=source))
        assert len(links) == 1
        assert links[0].enabled is True
        assert links[0].destination.type == ExternalDataDestination.Type.POSTHOG_WAREHOUSE
        if existing_destination:
            assert links[0].destination_id == existing_destination.pk
        assert (
            ExternalDataDestination.objects.for_team(self.team.pk)
            .filter(type=ExternalDataDestination.Type.POSTHOG_WAREHOUSE, deleted=False)
            .count()
            == 1
        )

    def test_a_source_with_an_external_link_is_unchanged(self) -> None:
        source = self._source("src")
        external_destination = ExternalDataDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, type=ExternalDataDestination.Type.REDSHIFT, name="Redshift"
        )
        link = ExternalDataSourceDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, source=source, destination=external_destination, enabled=False
        )

        call_command("backfill_warehouse_source_destinations", live_run=True)

        links = list(ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source=source))
        assert len(links) == 1
        assert links[0].pk == link.pk
        assert links[0].destination_id == external_destination.pk
        assert links[0].enabled is False
        assert ExternalDataDestination.objects.for_team(self.team.pk).count() == 1

    def test_preview_creates_no_links_or_warehouse_destination(self) -> None:
        source = self._source("src")

        call_command("backfill_warehouse_source_destinations")

        assert not ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source=source).exists()
        assert not ExternalDataDestination.objects.for_team(self.team.pk).exists()

    def test_team_id_only_backfills_that_teams_sources(self) -> None:
        source = self._source("mine")
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_source = self._source("other", team=other_team)

        call_command("backfill_warehouse_source_destinations", team_id=self.team.pk, live_run=True)

        assert ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source=source).count() == 1
        assert not ExternalDataSourceDestination.objects.for_team(other_team.pk).filter(source=other_source).exists()
        assert not ExternalDataDestination.objects.for_team(other_team.pk).exists()

    def test_a_deleted_source_is_left_alone(self) -> None:
        # A deleted source never syncs again, so a link for it is noise the backfill should not add.
        source = self._source("deleted-source")
        source.deleted = True
        source.save(update_fields=["deleted"])

        call_command("backfill_warehouse_source_destinations", "--live-run")

        assert not ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source_id=source.pk).exists()

    def test_a_failed_link_makes_the_command_fail(self) -> None:
        source = self._source("src")

        with (
            patch.object(ExternalDataSourceDestination, "save", side_effect=RuntimeError("write failed")),
            self.assertRaisesMessage(CommandError, "1 source(s) could not be linked"),
        ):
            call_command("backfill_warehouse_source_destinations", "--live-run")

        assert not ExternalDataSourceDestination.objects.for_team(self.team.pk).filter(source=source).exists()


class TestDestinationIdsForRun(BaseTest):
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

    def _link(self, destination: ExternalDataDestination) -> None:
        ExternalDataSourceDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, source=self.source, destination=destination
        )

    def _destination(self, name: str, type_: str) -> ExternalDataDestination:
        return ExternalDataDestination.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, type=type_, name=name
        )

    def test_a_run_that_writes_only_to_the_warehouse_still_records_it(self) -> None:
        # The Syncs tab reads this to name where a run landed, and an empty list reads there as
        # "went nowhere" rather than "the warehouse".
        warehouse = get_or_create_warehouse_destination(self.team.pk)

        assert destination_ids_for_run(self.schema) == [str(warehouse.id)]

    def test_a_run_records_the_warehouse_alongside_an_external_destination(self) -> None:
        warehouse = get_or_create_warehouse_destination(self.team.pk)
        snowflake = self._destination("snowflake", ExternalDataDestination.Type.SNOWFLAKE)
        self._link(warehouse)
        self._link(snowflake)

        assert destination_ids_for_run(self.schema) == sorted([str(warehouse.id), str(snowflake.id)])

    def test_external_ids_leave_out_the_warehouse(self) -> None:
        # What the consumer keys a coalesced write on. Counting the warehouse here would stop
        # every sync in the fleet sharing a write, because every run now records it.
        warehouse = get_or_create_warehouse_destination(self.team.pk)
        snowflake = self._destination("snowflake", ExternalDataDestination.Type.SNOWFLAKE)

        assert external_destination_ids_for(self.team.pk, [str(warehouse.id), str(snowflake.id)]) == [str(snowflake.id)]
        assert external_destination_ids_for(self.team.pk, [str(warehouse.id)]) == []
        assert external_destination_ids_for(self.team.pk, []) == []

    def test_external_ids_ignore_another_teams_destination(self) -> None:
        other = Team.objects.create(organization=self.organization, name="other")
        theirs = ExternalDataDestination.objects.for_team(other.pk).create(
            team_id=other.pk, type=ExternalDataDestination.Type.SNOWFLAKE, name="theirs"
        )

        assert external_destination_ids_for(self.team.pk, [str(theirs.id)]) == []
