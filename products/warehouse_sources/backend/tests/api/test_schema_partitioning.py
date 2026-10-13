from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition import RepartitionTarget

COLUMNS = {
    "id": {"clickhouse": "String", "hogql": "StringDatabaseField", "valid": True},
    "occurred_at": {"clickhouse": "Nullable(DateTime64(6, 'UTC'))", "hogql": "DateTimeDatabaseField", "valid": True},
    "billing_day": {"clickhouse": "Date", "hogql": "DateDatabaseField", "valid": True},
}


class TestSchemaPartitioning(APIBaseTest):
    def _schema(self, **overrides: Any) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.POSTGRES)
        table = DataWarehouseTable.objects.create(team=self.team, name="events", columns=COLUMNS)
        fields: dict[str, Any] = {
            "name": "events",
            "team": self.team,
            "source": source,
            "table": table,
            "should_sync": True,
            "sync_type": ExternalDataSchema.SyncType.APPEND,
            "sync_type_config": {
                "incremental_field": "occurred_at",
                "partition_mode": "md5",
                "partition_count": 8,
                "partitioning_keys": ["id"],
            },
        }
        fields.update(overrides)
        return ExternalDataSchema.objects.create(**fields)

    def _post(self, schema: ExternalDataSchema, body: dict[str, Any]) -> Any:
        return self.client.post(f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}/partitioning/", body)

    def test_staging_queues_a_rewrite_the_pipeline_can_read_and_keeps_the_rest_of_the_config(self) -> None:
        schema = self._schema()

        response = self._post(schema, {"column": "occurred_at", "date_granularity": "day"})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {
            "mode": "md5",
            "columns": ["id"],
            "date_granularity": None,
            "change_pending": True,
            "available_columns": ["billing_day", "occurred_at"],
        }
        schema.refresh_from_db()
        target = RepartitionTarget.from_dict(schema.sync_type_config["repartition_pending"])
        assert (target.partition_mode, target.partition_keys, target.partition_format) == (
            "datetime",
            ["occurred_at"],
            "day",
        )
        assert schema.sync_type_config["incremental_field"] == "occurred_at"
        assert schema.sync_type_config["partition_mode"] == "md5"

    @parameterized.expand(
        [
            ("column_is_not_a_date", {}, {"column": "id", "date_granularity": "day"}),
            ("hour_on_a_date_only_column", {}, {"column": "billing_day", "date_granularity": "hour"}),
            (
                "full_refresh_table",
                {"sync_type": ExternalDataSchema.SyncType.FULL_REFRESH},
                {"column": "occurred_at", "date_granularity": "day"},
            ),
            ("sync_is_off", {"should_sync": False}, {"column": "occurred_at", "date_granularity": "day"}),
            ("table_not_synced_yet", {"table": None}, {"column": "occurred_at", "date_granularity": "day"}),
            (
                "rewrite_already_queued",
                {"sync_type_config": {"repartition_pending": {"partition_mode": "md5", "partition_keys": ["id"]}}},
                {"column": "occurred_at", "date_granularity": "day"},
            ),
            (
                "swap_in_progress",
                {"sync_type_config": {"repartition_swap": {"state": "ready"}}},
                {"column": "occurred_at", "date_granularity": "day"},
            ),
            (
                "already_this_layout",
                {
                    "sync_type_config": {
                        "partition_mode": "datetime",
                        "partition_format": "day",
                        "partitioning_keys": ["occurred_at"],
                    }
                },
                {"column": "occurred_at", "date_granularity": "day"},
            ),
        ]
    )
    def test_a_refused_change_leaves_the_config_as_it_was(
        self, _name: str, overrides: dict[str, Any], body: dict[str, Any]
    ) -> None:
        schema = self._schema(**overrides)
        config_before = dict(schema.sync_type_config)

        response = self._post(schema, body)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.json()["detail"]
        schema.refresh_from_db()
        assert schema.sync_type_config == config_before
