import pytest
from unittest.mock import patch

from posthog.models import Organization

from products.managed_warehouse.backend.facade.api import get_duckgres_query_server_config, get_stored_warehouse_config
from products.managed_warehouse.backend.facade.contracts import DuckgresStoredServerConfig
from products.managed_warehouse.backend.models import DuckgresServer


def test_query_server_config_maps_legacy_environment_config_to_a_contract() -> None:
    with patch(
        "products.managed_warehouse.backend.common.get_duckgres_config_for_org",
        return_value={
            "DUCKGRES_HOST": "warehouse.example.com",
            "DUCKGRES_PORT": "6543",
            "DUCKGRES_FLIGHT_PORT": "8816",
            "DUCKGRES_DATABASE": "ducklake",
            "DUCKGRES_USERNAME": "root",
            "DUCKGRES_PASSWORD": "password",
        },
    ):
        config = get_duckgres_query_server_config("organization-id")

    assert config.host == "warehouse.example.com"
    assert config.port == 6543
    assert config.flight_port == 8816
    assert config.database == "ducklake"


@pytest.mark.django_db
def test_stored_warehouse_config_maps_connection_and_catalog_without_returning_the_model() -> None:
    organization = Organization.objects.create(name="Stored config")
    DuckgresServer.objects.create(
        organization=organization,
        host="warehouse.example.com",
        port=6543,
        flight_port=8816,
        database="ducklake",
        username="root",
        password="query-password",
        catalog_host="catalog.example.com",
        catalog_port=5433,
        catalog_database="catalog",
        catalog_username="catalog-user",
        catalog_password="catalog-password",
        bucket="managed-warehouse-bucket",
        bucket_region="eu-central-1",
    )

    with patch("products.managed_warehouse.backend.common.is_dev_mode", return_value=False):
        stored = get_stored_warehouse_config(str(organization.id))

    assert isinstance(stored, DuckgresStoredServerConfig)
    assert stored.query_server.host == "warehouse.example.com"
    assert stored.catalog is not None
    assert stored.catalog.host == "catalog.example.com"
    assert stored.bucket is not None
    assert stored.bucket.bucket == "managed-warehouse-bucket"
    assert not hasattr(stored, "save")
