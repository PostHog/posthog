from posthog.models import Team

from products.data_tools.backend.facade.models import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

WAREHOUSE_ACCESS_CONTROL_FLAG = "posthog.hogql.database.database._evaluate_warehouse_access_control_flag"


def filter_through_warehouse_join(team: Team) -> dict[str, str]:
    credential = DataWarehouseCredential.objects.create(access_key="k", access_secret="s", team=team)
    DataWarehouseTable.objects.create(
        name="denied_warehouse_table",
        format=DataWarehouseTable.TableFormat.Parquet,
        team=team,
        credential=credential,
        url_pattern="s3://bucket/denied/*",
        columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "valid": True}},
    )
    DataWarehouseJoin.objects.create(
        team=team,
        source_table_name="persons",
        source_table_key="properties.email",
        joining_table_name="denied_warehouse_table",
        joining_table_key="id",
        field_name="denied_join",
    )
    return {"type": "data_warehouse_person_property", "key": "denied_join.id", "value": "internal", "operator": "exact"}
