from typing import Any

import pytest
from posthog.test.base import BaseTest

import requests_mock

from products.warehouse_sources.backend.migration.crawl import crawl_migration
from products.warehouse_sources.backend.migration.fivetran.client import FIVETRAN_API_URL, FivetranAuthError
from products.warehouse_sources.backend.migration.fivetran.planner import SourceMatchLike
from products.warehouse_sources.backend.migration.types import Verdict
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.types import ExternalDataSourceType


class _HubspotOnly:
    class _Match:
        source_type = ExternalDataSourceType.HUBSPOT
        table_aliases: dict[str, str] = {}
        config_keys: dict[str, str] = {}
        notes: tuple[str, ...] = ()

    def match_source(self, provider: str, vendor_service: str) -> SourceMatchLike | None:
        return self._Match() if vendor_service == "hubspot" else None

    def match_destination(self, provider: str, vendor_service: str) -> str | None:
        return None


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"json": {"code": "Success", "data": data}}


def _mock_account(m: requests_mock.Mocker, connection_ids: list[str]) -> None:
    m.get(f"{FIVETRAN_API_URL}/account/info", **_ok({"account_id": "acct_example", "account_name": "Example Co"}))
    m.get(f"{FIVETRAN_API_URL}/groups", **_ok({"items": []}))
    m.get(f"{FIVETRAN_API_URL}/connections", **_ok({"items": [{"id": cid} for cid in connection_ids]}))
    for cid in connection_ids:
        m.get(
            f"{FIVETRAN_API_URL}/connections/{cid}",
            **_ok({"id": cid, "service": "hubspot", "schema": cid, "sync_frequency": 360}),
        )
        m.get(f"{FIVETRAN_API_URL}/connections/{cid}/schemas", status_code=404, json={"message": "Not found"})


class TestCrawlMigration(BaseTest):
    def _migration(self) -> WarehouseMigration:
        return WarehouseMigration.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            created_by=self.user,
            provider=WarehouseMigration.Provider.FIVETRAN,
            credentials={"api_key": "fake-key", "api_secret": "fake-secret"},
        )

    def _items(self, migration: WarehouseMigration) -> dict[str, WarehouseMigrationItem]:
        items = WarehouseMigrationItem.objects.for_team(self.team.pk).filter(migration=migration)
        return {item.vendor_connection_id: item for item in items}

    def test_refresh_keeps_applied_items_and_replaces_the_rest(self) -> None:
        migration = self._migration()
        with requests_mock.Mocker() as m:
            _mock_account(m, ["conn_applied", "conn_pending", "conn_removed"])
            assert crawl_migration(team_id=self.team.pk, migration_id=migration.id, catalog=_HubspotOnly()) == 3

        items = self._items(migration)
        applied = items["conn_applied"]
        applied.status = WarehouseMigrationItem.Status.APPLIED
        applied.caveats = ["kept from the first crawl"]
        applied.save()

        with requests_mock.Mocker() as m:
            _mock_account(m, ["conn_applied", "conn_pending", "conn_new"])
            crawl_migration(team_id=self.team.pk, migration_id=migration.id, catalog=_HubspotOnly())

        migration.refresh_from_db()
        items = self._items(migration)
        assert migration.status == WarehouseMigration.Status.READY
        assert migration.account_name == "Example Co"
        assert set(items) == {"conn_applied", "conn_pending", "conn_new"}
        assert items["conn_applied"].caveats == ["kept from the first crawl"]
        assert items["conn_new"].verdict == Verdict.CAVEATS
        assert items["conn_new"].proposal is not None
        assert items["conn_new"].proposal["source_type"] == ExternalDataSourceType.HUBSPOT

    def test_rejected_key_marks_the_migration_failed(self) -> None:
        migration = self._migration()
        with requests_mock.Mocker() as m:
            m.get(f"{FIVETRAN_API_URL}/account/info", status_code=401, json={"message": "Unauthorized"})
            with pytest.raises(FivetranAuthError):
                crawl_migration(team_id=self.team.pk, migration_id=migration.id, catalog=_HubspotOnly())

        migration.refresh_from_db()
        assert migration.status == WarehouseMigration.Status.FAILED
        assert "rejected the API key" in migration.latest_error
