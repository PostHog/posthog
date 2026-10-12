from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from unittest.mock import patch

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import TableNode

from products.managed_warehouse.backend.external_tables import enroll_external_table
from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTableNames
from products.managed_warehouse.backend.models import ManagedWarehouseExternalTable
from products.managed_warehouse.backend.table_binding import build_trino_table_locators
from products.warehouse_sources.backend.facade.external_delta import get_external_delta_table, normalize_delta_s3_uri
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

if TYPE_CHECKING:
    from posthog.models import Team


@pytest.mark.parametrize(
    "url, expected",
    [
        ("s3://example-bucket/orders/", "s3://example-bucket/orders"),
        ("https://example-bucket.s3.amazonaws.com/orders/", "s3://example-bucket/orders"),
        ("https://example-bucket.s3.eu-central-1.amazonaws.com/orders/*.parquet", "s3://example-bucket/orders"),
    ],
)
def test_normalize_external_delta_location(url: str, expected: str) -> None:
    assert normalize_delta_s3_uri(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/orders",
        "http://example-bucket.s3.amazonaws.com/orders",
        "s3://example-bucket/orders?token=example",
        "s3://example-bucket/orders/*/part.parquet",
        "s3://example-bucket/%2e%2e/orders",
        "s3://user:password@example-bucket/orders",
        "s3://example-bucket/orders/{date}",
    ],
)
def test_external_delta_locations_reject_arbitrary_hosts_and_patterns(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_delta_s3_uri(url)


@pytest.mark.django_db
@pytest.mark.parametrize("published", [False, True])
def test_external_binding_requires_a_published_snapshot_and_current_source(team: Team, published: bool) -> None:
    table = DataWarehouseTable.objects.create(
        team=team,
        name="external_orders",
        format="Delta",
        url_pattern="s3://example-bucket/orders",
        columns={"id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField", "valid": True}},
    )
    with patch(
        "products.managed_warehouse.backend.external_tables.duckgres_data_imports_schema", return_value="imports"
    ):
        enrolled = enroll_external_table(team.id, table.id)
    if published:
        ManagedWarehouseExternalTable.objects.for_team(team.id).filter(id=enrolled.id).update(published_version=1)
    database = Database()
    database.tables.children["external_orders"] = TableNode(name="external_orders", table=table.hogql_definition())
    names = ManagedWarehouseTableNames(events_table="events", persons_table="persons", data_imports_schema="imports")
    with patch(
        "products.managed_warehouse.backend.facade.team_state.data_imports_table_naming_version", return_value="copy_v1"
    ):
        locators = build_trino_table_locators(database, team.id, catalog_name="tenant", table_names=names)
        assert ("external_orders" in locators) is published
        if published:
            assert locators["external_orders"] == ("tenant", "imports", f"external_{table.id.hex}")
        DataWarehouseTable.raw_objects.filter(id=table.id).update(url_pattern="s3://example-bucket/changed")
        locators = build_trino_table_locators(database, team.id, catalog_name="tenant", table_names=names)
    assert "external_orders" not in locators


@pytest.mark.django_db
def test_external_enrollment_is_project_scoped(team: Team) -> None:
    table = DataWarehouseTable.objects.create(
        team=team, name="orders", format="Delta", url_pattern="s3://example-bucket/orders"
    )
    with pytest.raises(ValueError, match="does not exist"):
        get_external_delta_table(team.id + 1, table.id)
    with pytest.raises(ValueError, match="does not exist"):
        get_external_delta_table(team.id, uuid.uuid4())
    assert not ManagedWarehouseExternalTable.objects.for_team(team.id).exists()
