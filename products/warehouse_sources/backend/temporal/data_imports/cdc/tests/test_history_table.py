import uuid

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import HISTORY_NAMING, LEGACY_HISTORY_NAMING
from products.warehouse_sources.backend.temporal.data_imports.cdc.history_table import (
    HistoryTableNameTakenError,
    history_naming,
    history_tables,
    is_another_schemas_history_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import build_table_name


class TestHistoryNaming(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team, source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), source_type="Postgres"
        )
        self.schema = ExternalDataSchema.objects.create(
            name="orders",
            team=self.team,
            source=self.source,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_table_mode": "both"},
        )

    def _table(self, storage_name: str, options: dict | None = None) -> DataWarehouseTable:
        return DataWarehouseTable.objects.create(
            team=self.team,
            name=build_table_name(self.source, storage_name),
            format="DeltaS3Wrapper",
            url_pattern=f"s3://bucket/{storage_name}",
            external_data_source=self.source,
            options=options or {},
        )

    @parameterized.expand(
        [
            ("no_history_table_yet", None, None, HISTORY_NAMING),
            ("legacy_table_without_the_marker", "orders_cdc", {}, LEGACY_HISTORY_NAMING),
            ("legacy_table_with_the_marker", "orders_cdc", {"history_table": True}, LEGACY_HISTORY_NAMING),
            (
                "stamped_new_table",
                "orders_history",
                {"history_table": True, "history_naming": "ph_validity"},
                HISTORY_NAMING,
            ),
        ]
    )
    def test_reads_the_naming_from_the_registered_table(
        self, _name: str, storage_name: str | None, options: dict | None, expected: object
    ) -> None:
        if storage_name is not None:
            self._table(storage_name, options)

        assert history_naming(self.schema) == expected

    def test_refuses_a_name_another_table_holds(self) -> None:
        self._table("orders_history")

        with pytest.raises(HistoryTableNameTakenError):
            history_naming(self.schema)

    @parameterized.expand([("syncing", True, True), ("discovered_only", False, False)])
    def test_refuses_a_name_a_sibling_table_syncs_under(self, _name: str, should_sync: bool, refused: bool) -> None:
        ExternalDataSchema.objects.create(
            name="orders_history", team=self.team, source=self.source, should_sync=should_sync
        )

        if refused:
            with pytest.raises(HistoryTableNameTakenError):
                history_naming(self.schema)
        else:
            assert history_naming(self.schema) == HISTORY_NAMING

    def test_a_schema_cannot_take_the_name_of_another_schemas_history_table(self) -> None:
        self._table("orders_history", {"history_table": True, "history_naming": "ph_validity"})
        sibling = ExternalDataSchema.objects.create(name="orders_history", team=self.team, source=self.source)

        assert is_another_schemas_history_table(sibling)
        assert not is_another_schemas_history_table(self.schema)

    def test_history_tables_finds_marked_and_unmarked_legacy_tables(self) -> None:
        legacy = self._table("orders_cdc")
        marked = self._table("other_history", {"history_table": True})
        self._table("orders")
        self._table("customer_cdc")

        assert set(history_tables(self.source)) == {legacy, marked}
