import pytest

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import companion_resource_name
from products.warehouse_sources.backend.temporal.data_imports.cdc.companion_table import deregister_companion_table

pytestmark = [pytest.mark.django_db]


@pytest.mark.parametrize("other_schema", ["links_the_table", "has_the_table_name", None])
def test_deregister_leaves_a_same_named_table_that_another_schema_owns(team, other_schema: str | None) -> None:
    source = ExternalDataSource.objects.create(team=team, source_type="Postgres")
    schema = ExternalDataSchema.objects.create(team=team, source=source, name="orders")
    table = DataWarehouseTable.objects.create(
        team=team,
        external_data_source=source,
        name=f"postgres_{companion_resource_name(schema.name)}",
        format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        url_pattern="https://bucket.example.com/orders_history/",
    )
    if other_schema is not None:
        # A cdc_only schema links its own history table, not the table that carries its name.
        ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name=companion_resource_name(schema.name),
            table=table if other_schema == "links_the_table" else None,
        )

    assert deregister_companion_table(schema) is (other_schema is None)

    table.refresh_from_db()
    assert table.deleted is (other_schema is None)
