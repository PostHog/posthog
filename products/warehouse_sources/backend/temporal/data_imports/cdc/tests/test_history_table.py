import uuid
from io import StringIO

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    HISTORY_NAMING,
    LEGACY_HISTORY_NAMING,
    HistoryNaming,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.history_table import (
    HistoryTableNameTakenError,
    history_naming,
    history_tables,
    is_another_schemas_history_table,
    new_history_names_taken,
    pin_history_naming,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import build_table_name

_PH_HISTORY_NAMING_FLAG = (
    "products.warehouse_sources.backend.temporal.data_imports.cdc.history_table.is_source_flag_enabled"
)


@patch(_PH_HISTORY_NAMING_FLAG, new=lambda *_: True)
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

    def test_a_new_history_table_keeps_the_legacy_naming_until_the_flag_is_on(self) -> None:
        with patch(_PH_HISTORY_NAMING_FLAG, new=lambda *_: False):
            assert history_naming(self.schema) == LEGACY_HISTORY_NAMING

    @parameterized.expand(
        [("pinned_new_flag_off", HISTORY_NAMING, False), ("pinned_legacy_flag_on", LEGACY_HISTORY_NAMING, True)]
    )
    def test_a_pinned_naming_wins_over_the_flag(self, _name: str, pinned: HistoryNaming, flag_on: bool) -> None:
        pin_history_naming(self.schema.sync_type_config, pinned)
        self.schema.save()

        with patch(_PH_HISTORY_NAMING_FLAG, new=lambda *_: flag_on):
            assert history_naming(self.schema) == pinned

    def test_a_stamped_new_table_wins_over_a_legacy_named_table(self) -> None:
        # An unlinked `orders_cdc` can be a source table that has not synced yet. Taking the legacy naming
        # for it would stop writing the stamped history table.
        self._table("orders_history", {"history_table": True, "history_naming": "ph_validity"})
        self._table("orders_cdc")

        assert history_naming(self.schema) == HISTORY_NAMING

    def test_a_sibling_whose_catalog_name_differs_does_not_block_history(self) -> None:
        # `ordersHistory` normalizes to the same folder leaf, but each schema's folder carries its id.
        ExternalDataSchema.objects.create(name="ordersHistory", team=self.team, source=self.source, should_sync=True)

        assert history_naming(self.schema) == HISTORY_NAMING

    @parameterized.expand(
        [("new_naming", HISTORY_NAMING, "orders_history"), ("legacy_naming", LEGACY_HISTORY_NAMING, "orders_cdc")]
    )
    def test_new_history_names_taken_compares_the_payload_of_a_new_source(
        self, _name: str, naming: HistoryNaming, sibling: str
    ) -> None:
        taken = new_history_names_taken(self.source, naming, ["orders", "items"], ["orders", sibling, "items"])

        assert taken == ["orders"]

    def test_a_sibling_source_table_named_like_the_legacy_table_is_not_its_history(self) -> None:
        sibling = ExternalDataSchema.objects.create(name="orders_cdc", team=self.team, source=self.source)
        sibling.table = self._table("orders_cdc")
        sibling.save()

        assert history_naming(self.schema) == HISTORY_NAMING

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

    @parameterized.expand(
        [
            ("new_table", "orders_history", {"history_table": True, "history_naming": "ph_validity"}),
            # A history table that stopped syncing before the marker existed never got it.
            ("unmarked_legacy_table", "orders_cdc", {}),
        ]
    )
    def test_a_schema_cannot_take_the_name_of_another_schemas_history_table(
        self, _name: str, storage_name: str, options: dict
    ) -> None:
        self._table(storage_name, options)
        sibling = ExternalDataSchema.objects.create(name=storage_name, team=self.team, source=self.source)

        assert is_another_schemas_history_table(sibling)
        assert not is_another_schemas_history_table(self.schema)

    # A schema renamed by the multi-schema migration keeps its pinned catalog name, not the name of its row.
    @parameterized.expand([("unpinned", None, True), ("pinned_to_old_name", "orders_history", False)])
    def test_the_reverse_guard_compares_the_catalog_name(
        self, _name: str, s3_folder_name: str | None, refused: bool
    ) -> None:
        # `orders` would own `orders_history` itself.
        self.schema.sync_type_config = {"cdc_table_mode": "consolidated"}
        self.schema.save()
        ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=self.source,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_table_mode": "both"},
        )
        sibling = ExternalDataSchema.objects.create(
            name="public.orders_history", team=self.team, source=self.source, s3_folder_name=s3_folder_name
        )

        assert is_another_schemas_history_table(sibling) == refused

    def test_history_tables_finds_marked_and_unmarked_legacy_tables(self) -> None:
        legacy = self._table("orders_cdc")
        marked = self._table("other_history", {"history_table": True})
        self._table("orders")
        self._table("customer_cdc")
        # A discovered `orders_cdc` source table that does not sync owns no table, so the legacy table above
        # is still the history of `orders`.
        ExternalDataSchema.objects.create(name="orders_cdc", team=self.team, source=self.source)
        # `items_cdc` syncs into its own table, which is not the history of `items`.
        ExternalDataSchema.objects.create(name="items", team=self.team, source=self.source)
        ExternalDataSchema.objects.create(
            name="items_cdc", team=self.team, source=self.source, table=self._table("items_cdc")
        )

        assert set(history_tables(self.source)) == {legacy, marked}

    @parameterized.expand([("preview", False), ("live_run", True)])
    def test_backfill_marks_unmarked_legacy_history_tables(self, _name: str, live_run: bool) -> None:
        legacy = self._table("orders_cdc")
        ExternalDataSchema.objects.create(name="items", team=self.team, source=self.source)
        own_table = self._table("items_cdc")
        ExternalDataSchema.objects.create(name="items_cdc", team=self.team, source=self.source, table=own_table)

        call_command("backfill_history_table_marker", *(["--live-run"] if live_run else []), stdout=StringIO())

        legacy.refresh_from_db()
        own_table.refresh_from_db()
        assert legacy.is_history_table is live_run
        assert not own_table.is_history_table
