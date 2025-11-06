import os
import asyncio
from collections.abc import Generator
from io import BytesIO
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from unittest.mock import patch

import backoff
import aioboto3
from asgiref.sync import sync_to_async
from dagster_pipes import PipesContext
from fastavro import reader
from pydantic_avro import AvroBase

from posthog.models import GroupTypeMapping, Organization, Project, PropertyDefinition, Team, User

from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.enterprise.backend.hogai.eval.schema import (
    ActorsPropertyTaxonomySnapshot,
    DataWarehouseTableSnapshot,
    EvalsDockerImageConfig,
    GroupTypeMappingSnapshot,
    PropertyDefinitionSnapshot,
    PropertyTaxonomySnapshot,
    TeamEvaluationSnapshot,
    TeamSnapshot,
    TeamTaxonomyItemSnapshot,
)

from .query_patches import (
    ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE,
    EVENT_TAXONOMY_QUERY_DATA_SOURCE,
    TEAM_TAXONOMY_QUERY_DATA_SOURCE,
    PatchedActorsPropertyTaxonomyQueryRunner,
    PatchedEventTaxonomyQueryRunner,
    PatchedTeamTaxonomyQueryRunner,
)

if TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client


T = TypeVar("T", bound=AvroBase)


class SnapshotLoader:
    """Loads snapshots from S3, restores Django models, and patches query runners."""

    def __init__(self, context: PipesContext, config: EvalsDockerImageConfig):
        self.context = context
        self.config = config
        self.patches: list[Any] = []

    async def load_snapshots(self) -> tuple[Organization, User]:
        self.organization = await Organization.objects.acreate(name="PostHog")
        self.user = await sync_to_async(User.objects.create_and_join)(self.organization, "test@posthog.com", "12345678")

        for snapshot in self.config.team_snapshots:
            self.context.log.info(f"Loading Postgres snapshot for team {snapshot.team_id}...")

            project = await Project.objects.acreate(
                id=await sync_to_async(Team.objects.increment_id_sequence)(), organization=self.organization
            )

            (
                project_snapshot_bytes,
                property_definitions_snapshot_bytes,
                group_type_mappings_snapshot_bytes,
                data_warehouse_tables_snapshot_bytes,
                event_taxonomy_snapshot_bytes,
                properties_taxonomy_snapshot_bytes,
                actors_property_taxonomy_snapshot_bytes,
            ) = await self._get_all_snapshots(snapshot)

            team = await self._load_team_snapshot(project, snapshot.team_id, project_snapshot_bytes)
            await asyncio.gather(
                self._load_property_definitions(property_definitions_snapshot_bytes, team=team, project=project),
                self._load_group_type_mappings(group_type_mappings_snapshot_bytes, team=team, project=project),
                self._load_data_warehouse_tables(data_warehouse_tables_snapshot_bytes, team=team, project=project),
            )
            self._load_event_taxonomy(event_taxonomy_snapshot_bytes, team=team)
            self._load_properties_taxonomy(properties_taxonomy_snapshot_bytes, team=team)
            self._load_actors_property_taxonomy(actors_property_taxonomy_snapshot_bytes, team=team)

        self._patch_query_runners()

        return self.organization, self.user

    def cleanup(self):
        for mock in self.patches:
            mock.stop()

    @backoff.on_exception(backoff.expo, Exception, max_tries=3)
    async def _get_all_snapshots(self, snapshot: TeamEvaluationSnapshot):
        async with aioboto3.Session().client(
            "s3",
            endpoint_url=self.config.aws_endpoint_url,
            aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY"),
        ) as client:
            loaded_snapshots = await asyncio.gather(
                self._get_snapshot_from_s3(client, snapshot.postgres.team),
                self._get_snapshot_from_s3(client, snapshot.postgres.property_definitions),
                self._get_snapshot_from_s3(client, snapshot.postgres.group_type_mappings),
                self._get_snapshot_from_s3(client, snapshot.postgres.data_warehouse_tables),
                self._get_snapshot_from_s3(client, snapshot.clickhouse.event_taxonomy),
                self._get_snapshot_from_s3(client, snapshot.clickhouse.properties_taxonomy),
                self._get_snapshot_from_s3(client, snapshot.clickhouse.actors_property_taxonomy),
            )
            return loaded_snapshots

    async def _get_snapshot_from_s3(self, client: "S3Client", file_key: str):
        response = await client.get_object(Bucket=self.config.aws_bucket_name, Key=file_key)
        content = await response["Body"].read()
        return BytesIO(content)

    def _parse_snapshot_to_schema(self, schema: type[T], buffer: BytesIO) -> Generator[T, None, None]:
        for record in reader(buffer):
            yield schema.model_validate(record)

    async def _load_team_snapshot(self, project: Project, team_id: int, buffer: BytesIO) -> Team:
        team_snapshot = next(self._parse_snapshot_to_schema(TeamSnapshot, buffer))
        team = next(TeamSnapshot.deserialize_for_team([team_snapshot], team_id=team_id, project_id=project.id))
        team.project = project
        team.organization = self.organization
        team.api_token = f"team_{team_id}"
        await team.asave()
        return team

    async def _load_property_definitions(self, buffer: BytesIO, *, team: Team, project: Project):
        snapshot = list(self._parse_snapshot_to_schema(PropertyDefinitionSnapshot, buffer))
        property_definitions = PropertyDefinitionSnapshot.deserialize_for_team(
            snapshot, team_id=team.id, project_id=project.id
        )
        return await PropertyDefinition.objects.abulk_create(property_definitions, batch_size=500)

    async def _load_group_type_mappings(self, buffer: BytesIO, *, team: Team, project: Project):
        snapshot = list(self._parse_snapshot_to_schema(GroupTypeMappingSnapshot, buffer))
        group_type_mappings = GroupTypeMappingSnapshot.deserialize_for_team(
            snapshot, team_id=team.id, project_id=project.id
        )
        return await GroupTypeMapping.objects.abulk_create(group_type_mappings, batch_size=500)

    async def _load_data_warehouse_tables(self, buffer: BytesIO, *, team: Team, project: Project):
        snapshot = list(self._parse_snapshot_to_schema(DataWarehouseTableSnapshot, buffer))
        data_warehouse_tables = DataWarehouseTableSnapshot.deserialize_for_team(
            snapshot, team_id=team.id, project_id=project.id
        )
        return await DataWarehouseTable.objects.abulk_create(data_warehouse_tables, batch_size=500)

    def _load_event_taxonomy(self, buffer: BytesIO, *, team: Team):
        snapshot = next(self._parse_snapshot_to_schema(TeamTaxonomyItemSnapshot, buffer))
        TEAM_TAXONOMY_QUERY_DATA_SOURCE[team.id] = snapshot.results

    def _load_properties_taxonomy(self, buffer: BytesIO, *, team: Team):
        for item in self._parse_snapshot_to_schema(PropertyTaxonomySnapshot, buffer):
            EVENT_TAXONOMY_QUERY_DATA_SOURCE[team.id][item.event] = item.results

    def _load_actors_property_taxonomy(self, buffer: BytesIO, *, team: Team):
        for item in self._parse_snapshot_to_schema(ActorsPropertyTaxonomySnapshot, buffer):
            key: int | Literal["person"] = item.group_type_index if isinstance(item.group_type_index, int) else "person"
            ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE[team.pk][key][item.property] = item.results

    def _patch_query_runners(self):
        self.patches = [
            patch(
                "posthog.hogql_queries.ai.team_taxonomy_query_runner.TeamTaxonomyQueryRunner",
                new=PatchedTeamTaxonomyQueryRunner,
            ),
            patch(
                "posthog.hogql_queries.ai.event_taxonomy_query_runner.EventTaxonomyQueryRunner",
                new=PatchedEventTaxonomyQueryRunner,
            ),
            patch(
                "posthog.hogql_queries.ai.actors_property_taxonomy_query_runner.ActorsPropertyTaxonomyQueryRunner",
                new=PatchedActorsPropertyTaxonomyQueryRunner,
            ),
        ]
        for mock in self.patches:
            mock.start()
