from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import requests_mock
from parameterized import parameterized

from products.warehouse_sources.backend.migration.fivetran.client import FIVETRAN_API_URL
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem

_VIEWS = "products.warehouse_sources.backend.presentation.views.warehouse_migration"


class TestWarehouseMigrationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch(f"{_VIEWS}.is_migration_import_enabled", return_value=True)
        self.flag = flag.start()
        self.addCleanup(flag.stop)
        start = patch(f"{_VIEWS}.start_crawl", return_value="warehouse-migration-crawl-test")
        self.start_crawl: MagicMock = start.start()
        self.addCleanup(start.stop)
        self.url = f"/api/projects/{self.team.pk}/warehouse_migrations/"

    def _migration(self) -> WarehouseMigration:
        return WarehouseMigration.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            created_by=self.user,
            provider=WarehouseMigration.Provider.FIVETRAN,
            status=WarehouseMigration.Status.READY,
            credentials={"api_key": "fake-key", "api_secret": "fake-secret"},
        )

    def _item(self, migration: WarehouseMigration, **overrides: Any) -> WarehouseMigrationItem:
        fields: dict[str, Any] = {
            "team_id": self.team.pk,
            "migration": migration,
            "vendor_connection_id": f"conn_{uuid4().hex[:8]}",
            "vendor_service": "hubspot",
            "name": "hubspot",
            "verdict": WarehouseMigrationItem.Verdict.AS_IS,
            **overrides,
        }
        return WarehouseMigrationItem.objects.for_team(self.team.pk).create(**fields)

    def test_flag_off_hides_the_endpoint(self) -> None:
        self.flag.return_value = False
        assert self.client.get(self.url).status_code == 404

    @parameterized.expand([("rejected", 401, 400), ("accepted", 200, 201)])
    def test_create_checks_the_key_before_storing_it(self, _name: str, vendor_status: int, expected: int) -> None:
        with requests_mock.Mocker() as m:
            m.get(
                f"{FIVETRAN_API_URL}/account/info",
                status_code=vendor_status,
                json={"code": "Success", "data": {"account_id": "acct_example"}, "message": "Unauthorized"},
            )
            response = self.client.post(
                self.url, {"provider": "fivetran", "api_key": "fake-key", "api_secret": "fake-secret"}
            )

        assert response.status_code == expected, response.json()
        assert "fake-secret" not in response.content.decode()
        migrations = WarehouseMigration.objects.for_team(self.team.pk)
        if expected == 400:
            assert response.json()["attr"] == "api_key"
            assert not migrations.exists()
            self.start_crawl.assert_not_called()
        else:
            migration = migrations.get()
            assert migration.credentials == {"api_key": "fake-key", "api_secret": "fake-secret"}
            assert migration.workflow_id == "warehouse-migration-crawl-test"
            self.start_crawl.assert_called_once_with(team_id=self.team.pk, migration_id=migration.id)

    def test_items_and_counts_follow_skips(self) -> None:
        migration = self._migration()
        pending = self._item(migration)
        self._item(migration, verdict=WarehouseMigrationItem.Verdict.UNSUPPORTED)
        applied = self._item(migration, status=WarehouseMigrationItem.Status.APPLIED)

        skip = self.client.post(f"{self.url}{migration.id}/items/{pending.id}/skip/")
        assert skip.status_code == 200, skip.json()
        assert skip.json()["status"] == "skipped"
        assert self.client.post(f"{self.url}{migration.id}/items/{applied.id}/skip/").status_code == 400

        detail = self.client.get(f"{self.url}{migration.id}/").json()
        assert "credentials" not in detail
        assert detail["item_counts"] == {"as_is": 0, "caveats": 0, "unsupported": 1, "applied": 1, "skipped": 1}
        assert len(self.client.get(f"{self.url}{migration.id}/items/").json()) == 3

    def test_refresh_restarts_the_crawl_unless_one_is_running(self) -> None:
        migration = self._migration()
        assert self.client.post(f"{self.url}{migration.id}/refresh/").status_code == 200
        self.start_crawl.assert_called_once()
        migration.refresh_from_db()
        assert migration.status == WarehouseMigration.Status.PENDING
        assert self.client.post(f"{self.url}{migration.id}/refresh/").status_code == 400

    def test_other_team_cannot_read_a_migration(self) -> None:
        other_team = self.create_team_with_organization(organization=self.organization)
        migration = WarehouseMigration.objects.for_team(other_team.pk).create(
            team_id=other_team.pk, provider=WarehouseMigration.Provider.FIVETRAN
        )
        assert self.client.get(f"{self.url}{migration.id}/").status_code == 404
