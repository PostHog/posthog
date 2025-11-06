from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync

from posthog.schema import (
    ActorsPropertyTaxonomyQuery,
    ActorsPropertyTaxonomyResponse,
    EventTaxonomyItem,
    EventTaxonomyQuery,
    TeamTaxonomyItem,
    TeamTaxonomyQuery,
)

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import GroupTypeMapping, Organization, PropertyDefinition, Team

from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.enterprise.backend.hogai.eval.offline.query_patches import (
    ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE,
    EVENT_TAXONOMY_QUERY_DATA_SOURCE,
    TEAM_TAXONOMY_QUERY_DATA_SOURCE,
)
from products.enterprise.backend.hogai.eval.offline.snapshot_loader import SnapshotLoader
from products.enterprise.backend.hogai.eval.schema import (
    ActorsPropertyTaxonomySnapshot,
    ClickhouseTeamDataSnapshot,
    DataWarehouseTableSnapshot,
    EvalsDockerImageConfig,
    GroupTypeMappingSnapshot,
    PostgresTeamDataSnapshot,
    PropertyDefinitionSnapshot,
    PropertyTaxonomySnapshot,
    TeamSnapshot,
    TeamTaxonomyItemSnapshot,
)


class TestSnapshotLoader(BaseTest):
    def setUp(self):
        super().setUp()
        TEAM_TAXONOMY_QUERY_DATA_SOURCE.clear()
        EVENT_TAXONOMY_QUERY_DATA_SOURCE.clear()
        ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE.clear()

    def tearDown(self):
        TEAM_TAXONOMY_QUERY_DATA_SOURCE.clear()
        EVENT_TAXONOMY_QUERY_DATA_SOURCE.clear()
        ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE.clear()
        super().tearDown()

    def _extras(self, team_id: int) -> dict[str, Any]:
        return {
            "aws_endpoint_url": "http://localhost:9000",
            "aws_bucket_name": "evals",
            "experiment_name": "offline_evaluation",
            "team_snapshots": [
                {
                    "team_id": team_id,
                    "postgres": PostgresTeamDataSnapshot(
                        team=f"pg/team_{team_id}.avro",
                        property_definitions=f"pg/property_defs_{team_id}.avro",
                        group_type_mappings=f"pg/group_mappings_{team_id}.avro",
                        data_warehouse_tables=f"pg/dw_tables_{team_id}.avro",
                    ).model_dump(),
                    "clickhouse": ClickhouseTeamDataSnapshot(
                        event_taxonomy=f"ch/event_taxonomy_{team_id}.avro",
                        properties_taxonomy=f"ch/properties_taxonomy_{team_id}.avro",
                        actors_property_taxonomy=f"ch/actors_property_taxonomy_{team_id}.avro",
                    ).model_dump(),
                }
            ],
            "dataset": [],
            "experiment_id": "test_experiment_id",
            "experiment_name": "test_experiment_name",
            "dataset_id": "test_dataset_id",
            "dataset_name": "test_dataset_name",
            "dataset_inputs": [],
        }

    def _fake_parse(self, schema, _buffer):
        if schema is TeamSnapshot:
            yield TeamSnapshot(name="Evaluated Team", test_account_filters="{}")
            return
        if schema is PropertyDefinitionSnapshot:
            yield PropertyDefinitionSnapshot(
                name="$browser", is_numerical=False, property_type="String", type=1, group_type_index=None
            )
            yield PropertyDefinitionSnapshot(
                name="$device", is_numerical=False, property_type="String", type=1, group_type_index=0
            )
            return
        if schema is GroupTypeMappingSnapshot:
            yield GroupTypeMappingSnapshot(
                group_type="organization", group_type_index=0, name_singular="org", name_plural="orgs"
            )
            yield GroupTypeMappingSnapshot(
                group_type="company", group_type_index=1, name_singular="company", name_plural="companies"
            )
            return
        if schema is DataWarehouseTableSnapshot:
            yield DataWarehouseTableSnapshot(name="users", format="Parquet", columns=json.dumps({"id": "Int64"}))
            yield DataWarehouseTableSnapshot(name="orders", format="Parquet", columns=json.dumps({"id": "Int64"}))
            return
        if schema is TeamTaxonomyItemSnapshot:
            yield TeamTaxonomyItemSnapshot(
                results=[
                    TeamTaxonomyItem(count=123, event="$pageview"),
                    TeamTaxonomyItem(count=45, event="$autocapture"),
                ]
            )
            return
        if schema is PropertyTaxonomySnapshot:
            # Two events to fill EVENT_TAXONOMY_QUERY_DATA_SOURCE
            yield PropertyTaxonomySnapshot(
                event="$pageview",
                results=[
                    EventTaxonomyItem(property="$browser", sample_values=["Safari"], sample_count=10),
                    EventTaxonomyItem(property="$os", sample_values=["macOS"], sample_count=5),
                ],
            )
            yield PropertyTaxonomySnapshot(
                event="$autocapture",
                results=[
                    EventTaxonomyItem(property="$element_type", sample_values=["a"], sample_count=3),
                ],
            )
            return
        if schema is ActorsPropertyTaxonomySnapshot:
            # person (None), group 0, and group 1
            yield ActorsPropertyTaxonomySnapshot(
                group_type_index=None,
                property="$browser",
                results=ActorsPropertyTaxonomyResponse(sample_values=["Safari"], sample_count=10),
            )
            yield ActorsPropertyTaxonomySnapshot(
                group_type_index=0,
                property="$device",
                results=ActorsPropertyTaxonomyResponse(sample_values=["Phone"], sample_count=2),
            )
            yield ActorsPropertyTaxonomySnapshot(
                group_type_index=1,
                property="$industry",
                results=ActorsPropertyTaxonomyResponse(sample_values=["Tech"], sample_count=1),
            )
            return
        raise AssertionError(f"Unhandled schema in fake parser: {schema}")

    def _build_context(self, extras: dict[str, Any]) -> MagicMock:
        ctx = MagicMock()
        ctx.extras = extras
        ctx.log = MagicMock()
        ctx.log.info = MagicMock()
        return ctx

    def _load_with_mocks(self) -> tuple[Organization, Any, list[Any], Team]:
        extras = self._extras(9990)
        ctx = self._build_context(extras)

        async_get = AsyncMock(side_effect=lambda client, key: BytesIO(b"ok"))

        with patch.object(SnapshotLoader, "_get_snapshot_from_s3", new=async_get):
            with patch.object(SnapshotLoader, "_parse_snapshot_to_schema", new=self._fake_parse):
                config = EvalsDockerImageConfig.model_validate(ctx.extras)
                loader = SnapshotLoader(ctx, config)
                org, user = async_to_sync(loader.load_snapshots)()
        return org, user, config.dataset_inputs, Team.objects.get(id=9990)

    def test_loads_data_from_s3(self):
        team_id = 99990
        extras = self._extras(team_id)
        ctx = self._build_context(extras)

        calls: list[tuple[dict[str, Any], str]] = []

        async def record_call(_self, client, key: str):
            calls.append(({"Bucket": extras["aws_bucket_name"]}, key))
            return BytesIO(b"ok")

        with patch.object(SnapshotLoader, "_get_snapshot_from_s3", new=record_call):
            with patch.object(SnapshotLoader, "_parse_snapshot_to_schema", new=self._fake_parse):
                config = EvalsDockerImageConfig.model_validate(ctx.extras)
                loader = SnapshotLoader(ctx, config)
                async_to_sync(loader.load_snapshots)()

        keys = [k for _, k in calls]
        self.assertIn(f"pg/team_{team_id}.avro", keys)
        self.assertIn(f"pg/property_defs_{team_id}.avro", keys)
        self.assertIn(f"pg/group_mappings_{team_id}.avro", keys)
        self.assertIn(f"pg/dw_tables_{team_id}.avro", keys)
        self.assertIn(f"ch/event_taxonomy_{team_id}.avro", keys)
        self.assertIn(f"ch/properties_taxonomy_{team_id}.avro", keys)
        self.assertIn(f"ch/actors_property_taxonomy_{team_id}.avro", keys)

    def test_restores_org_team_user(self):
        org, user, _dataset, team = self._load_with_mocks()
        self.assertEqual(org.name, "PostHog")
        self.assertEqual(team.organization_id, org.id)
        self.assertEqual(team.id, 9990)
        self.assertEqual(team.api_token, "team_9990")

    def test_restores_models_counts(self):
        _org, _user, _dataset, team = self._load_with_mocks()
        self.assertEqual(PropertyDefinition.objects.filter(team_id=team.id).count(), 2)
        self.assertEqual(GroupTypeMapping.objects.filter(team_id=team.id).count(), 2)
        self.assertEqual(DataWarehouseTable.objects.filter(team_id=team.id).count(), 2)

    def test_loads_team_taxonomy_data_source(self):
        _org, _user, _dataset, team = self._load_with_mocks()
        self.assertIn(team.id, TEAM_TAXONOMY_QUERY_DATA_SOURCE)
        self.assertEqual([i.event for i in TEAM_TAXONOMY_QUERY_DATA_SOURCE[team.id]], ["$pageview", "$autocapture"])

    def test_loads_event_taxonomy_data_source(self):
        _org, _user, _dataset, team = self._load_with_mocks()
        self.assertIn("$pageview", EVENT_TAXONOMY_QUERY_DATA_SOURCE[team.id])
        self.assertIn("$autocapture", EVENT_TAXONOMY_QUERY_DATA_SOURCE[team.id])
        props = [i.property for i in EVENT_TAXONOMY_QUERY_DATA_SOURCE[team.id]["$pageview"]]
        self.assertIn("$browser", props)
        self.assertIn("$os", props)

    def test_loads_actors_property_taxonomy_data_source_various_group_types(self):
        _org, _user, _dataset, team = self._load_with_mocks()
        self.assertIn("person", ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE[team.id])
        self.assertIn(0, ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE[team.id])
        self.assertIn(1, ACTORS_PROPERTY_TAXONOMY_QUERY_DATA_SOURCE[team.id])

    def test_runs_query_runner_patches(self):
        _org, _user, _dataset, team = self._load_with_mocks()

        # Team taxonomy
        team_resp = get_query_runner(TeamTaxonomyQuery(), team=team).calculate()
        self.assertTrue(any(item.event == "$pageview" for item in team_resp.results))

        # Event taxonomy by event
        event_resp = get_query_runner(EventTaxonomyQuery(event="$pageview", maxPropertyValues=5), team=team).calculate()
        self.assertTrue(any(item.property == "$browser" for item in event_resp.results))

        # Actors property taxonomy for person
        actors_resp_person = get_query_runner(
            ActorsPropertyTaxonomyQuery(properties=["$browser"], groupTypeIndex=None),
            team=team,
        ).calculate()
        self.assertEqual(actors_resp_person.results[0].sample_values, ["Safari"])

        # Actors property taxonomy for group 0
        actors_resp_group0 = get_query_runner(
            ActorsPropertyTaxonomyQuery(properties=["$device"], groupTypeIndex=0),
            team=team,
        ).calculate()
        self.assertEqual(actors_resp_group0.results[0].sample_values, ["Phone"])

        # Actors property taxonomy for group 1
        actors_resp_group1 = get_query_runner(
            ActorsPropertyTaxonomyQuery(properties=["$industry"], groupTypeIndex=1),
            team=team,
        ).calculate()
        self.assertEqual(actors_resp_group1.results[0].sample_values, ["Tech"])
