import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Organization

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.api import (
    get_duckgres_query_server_config,
    get_stored_warehouse_config,
    is_data_modeling_shadow_ready,
)
from products.managed_warehouse.backend.facade.contracts import DuckgresStoredServerConfig
from products.managed_warehouse.backend.models import (
    DuckgresServer,
    ManagedWarehouseViewTranslationJob,
    ManagedWarehouseViewTranslationResult,
)
from products.managed_warehouse.backend.view_translation_status import source_query_hash


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


class TestDataModelingShadowReadiness(BaseTest):
    def test_requires_a_ready_trino_target_and_a_current_compiled_translation(self) -> None:
        query = {"kind": "HogQLQuery", "query": "SELECT 1"}
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="translated_view",
            query=query,
        )
        job = ManagedWarehouseViewTranslationJob.objects.create(organization=self.organization)
        result = ManagedWarehouseViewTranslationResult.all_teams.create(
            job=job,
            team=self.team,
            saved_query_id=saved_query.id,
            saved_query_name=saved_query.name,
            source_query_hash=source_query_hash(query),
            status=ManagedWarehouseViewTranslationResult.Status.COMPILED,
            trino_sql="SELECT 1",
        )

        def is_ready(source_query: object = query) -> bool:
            return is_data_modeling_shadow_ready(
                organization_id=self.organization.id,
                team_id=self.team.id,
                saved_query_id=saved_query.id,
                source_query=source_query,
            )

        readiness_target = "products.managed_warehouse.backend.view_translation_status.get_ready_trino_catalog_name"
        with patch(readiness_target, return_value=None):
            assert is_ready() is False

        with patch(readiness_target, return_value="managed_catalog"):
            assert is_ready() is True
            assert is_ready({"kind": "HogQLQuery", "query": "SELECT 2"}) is False

            result.trino_sql = ""
            result.save(update_fields=["trino_sql"])
            assert is_ready() is False

            result.trino_sql = "SELECT 1"
            result.status = ManagedWarehouseViewTranslationResult.Status.FAILED
            result.save(update_fields=["trino_sql", "status"])
            assert is_ready() is False
