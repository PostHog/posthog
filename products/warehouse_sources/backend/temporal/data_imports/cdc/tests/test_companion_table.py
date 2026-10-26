import pytest

from django.utils import timezone

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import HISTORY_TABLE_OPTION, DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import companion_resource_name
from products.warehouse_sources.backend.temporal.data_imports.cdc.companion_table import deregister_companion_table

pytestmark = [pytest.mark.django_db]


@pytest.mark.parametrize(
    ("sibling_name", "sibling_state", "marked", "expect_deregistered"),
    [
        ("orders_cdc", "links_the_table", False, False),
        # A cdc_only sibling links its own history table, not the table that carries its name.
        ("orders_cdc", "synced_unlinked", False, False),
        ("Orders_cdc", "synced_unlinked", False, False),
        ("orders_cdc", "never_synced", False, True),
        (None, None, False, True),
        # Registration marks the history table, and the marker settles ownership without the name check.
        ("orders_cdc", "synced_unlinked", True, True),
    ],
)
def test_deregister_leaves_a_same_named_table_that_another_schema_owns(
    team, sibling_name: str | None, sibling_state: str | None, marked: bool, expect_deregistered: bool
) -> None:
    source = ExternalDataSource.objects.create(team=team, source_type="Postgres")
    schema = ExternalDataSchema.objects.create(team=team, source=source, name="orders")
    table = DataWarehouseTable.objects.create(
        team=team,
        external_data_source=source,
        name=f"postgres_{companion_resource_name(schema.name)}",
        format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        url_pattern="https://bucket.example.com/orders_history/",
        options={HISTORY_TABLE_OPTION: True} if marked else {},
    )
    if sibling_name is not None:
        ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name=sibling_name,
            table=table if sibling_state == "links_the_table" else None,
            last_synced_at=None if sibling_state == "never_synced" else timezone.now(),
        )

    assert deregister_companion_table(schema) is expect_deregistered

    table.refresh_from_db()
    assert table.deleted is expect_deregistered
