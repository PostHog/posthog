import datetime as dt
from decimal import Decimal

import pytest
from unittest.mock import patch

from django.db.models.signals import post_delete, pre_delete

from posthog.models import Organization, Team

from products.managed_warehouse.backend.facade.api import (
    DuckgresUsageMirrorStale,
    duckgres_compute_rows_for_period,
    get_duckgres_query_server_config,
    get_stored_warehouse_config,
)
from products.managed_warehouse.backend.facade.contracts import DuckgresStoredServerConfig
from products.managed_warehouse.backend.models import DuckgresDailyUsage, DuckgresServer, DuckgresUsageCursor


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


def _usage(organization: Organization, team_id: int, total: int = 100) -> None:
    DuckgresDailyUsage.objects.create(
        date=dt.date(2026, 8, 30),
        organization_id=organization.id,
        team_id=team_id,
        query_source="standard",
        cpu=Decimal("8"),
        mem_gib=Decimal("16"),
        cpu_seconds=total,
        memory_seconds=0,
    )


@pytest.mark.django_db
def test_usage_read_reattributes_a_team_deleted_after_persistence() -> None:
    organization = Organization.objects.create(name="Deleted team")
    replacement = Team.objects.create(organization=organization, name="replacement")
    deleted = Team.objects.create(organization=organization, name="deleted")
    deleted_id = deleted.id
    _usage(organization, deleted_id)
    with patch.object(pre_delete, "send"), patch.object(post_delete, "send"):
        deleted.delete()

    with patch("products.managed_warehouse.backend.temporal.duckgres_usage.client.is_configured", return_value=False):
        rows = duckgres_compute_rows_for_period(dt.date(2026, 8, 30), dt.date(2026, 8, 30), endpoints=False)

    assert rows == [{"team_id": replacement.id, "total": 100}]
    assert DuckgresDailyUsage.objects.values_list("team_id", flat=True).get() == deleted_id


@pytest.mark.django_db
def test_usage_read_omits_and_alerts_when_deleted_team_has_no_replacement() -> None:
    organization = Organization.objects.create(name="No replacement")
    _usage(organization, team_id=999)

    with (
        patch("products.managed_warehouse.backend.temporal.duckgres_usage.client.is_configured", return_value=False),
        patch("products.managed_warehouse.backend.facade.api.logger") as logger,
    ):
        rows = duckgres_compute_rows_for_period(dt.date(2026, 8, 30), dt.date(2026, 8, 30), endpoints=False)

    assert rows == []
    logger.warning.assert_called_once()
    assert DuckgresDailyUsage.objects.count() == 1


@pytest.mark.django_db
def test_usage_read_does_not_reattribute_a_live_nonbillable_team() -> None:
    organization = Organization.objects.create(name="Nonbillable team")
    billable = Team.objects.create(organization=organization, name="billable")
    nonbillable = Team.objects.create(organization=organization, name="demo", is_demo=True)
    _usage(organization, team_id=nonbillable.id)

    with patch("products.managed_warehouse.backend.temporal.duckgres_usage.client.is_configured", return_value=False):
        rows = duckgres_compute_rows_for_period(dt.date(2026, 8, 30), dt.date(2026, 8, 30), endpoints=False)

    assert rows == [{"team_id": nonbillable.id, "total": 100}]
    assert rows[0]["team_id"] != billable.id


@pytest.mark.django_db
def test_complete_day_usage_read_requires_a_trusted_watermark() -> None:
    report_day = dt.date(2026, 8, 30)
    with (
        patch("products.managed_warehouse.backend.temporal.duckgres_usage.client.is_configured", return_value=True),
        pytest.raises(DuckgresUsageMirrorStale),
    ):
        duckgres_compute_rows_for_period(report_day, report_day, endpoints=False)

    DuckgresUsageCursor.objects.create(
        singleton=1,
        last_complete_watermark=dt.datetime(2026, 8, 31, tzinfo=dt.UTC),
    )
    with patch("products.managed_warehouse.backend.temporal.duckgres_usage.client.is_configured", return_value=True):
        assert duckgres_compute_rows_for_period(report_day, report_day, endpoints=False) == []


@pytest.mark.django_db
def test_initialized_usage_mirror_stays_freshness_gated_when_configuration_is_lost() -> None:
    report_day = dt.date(2026, 8, 30)
    DuckgresUsageCursor.objects.create(
        singleton=1,
        last_complete_watermark=dt.datetime(2026, 8, 30, tzinfo=dt.UTC),
    )

    with (
        patch("products.managed_warehouse.backend.temporal.duckgres_usage.client.is_configured", return_value=False),
        pytest.raises(DuckgresUsageMirrorStale),
    ):
        duckgres_compute_rows_for_period(report_day, report_day, endpoints=False)
