from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models import Team

from products.managed_warehouse.backend.models import ManagedWarehouseExternalTable
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestExternalTableSync(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.table = DataWarehouseTable.objects.create(
            team=self.team, name="external_orders", format="Delta", url_pattern="s3://example-bucket/orders"
        )
        self.url = f"/api/projects/{self.team.id}/warehouse_tables/{self.table.id}"
        self.flag = self.enterContext(
            patch("products.managed_warehouse.backend.external_tables._organization_flag_enabled", return_value=True)
        )
        self.enterContext(patch("products.managed_warehouse.backend.external_tables.is_dev_mode", return_value=True))
        self.enterContext(
            patch(
                "products.managed_warehouse.backend.external_tables.duckgres_data_imports_schema",
                return_value="imports",
            )
        )
        self.schedule = self.enterContext(
            patch("products.managed_warehouse.backend.external_tables._schedule_external_table")
        )

    def test_opt_in_starts_sync_and_opt_out_stops_refreshes(self) -> None:
        initial = self.client.get(f"{self.url}/warehouse_sync/")
        assert initial.status_code == 200
        assert initial.json()["enabled"] is False
        assert not ManagedWarehouseExternalTable.objects.for_team(self.team.id).exists()
        enabled = self.client.post(f"{self.url}/configure_warehouse_sync/", {"enabled": True, "interval_minutes": 15})
        assert enabled.status_code == 200
        assert enabled.json()["status"] == "preparing"
        self.schedule.assert_called_once_with(self.team.id, self.table.id, 15, trigger=True)
        row = ManagedWarehouseExternalTable.objects.for_team(self.team.id).get(table_id=self.table.id)
        row.published_version = 2
        row.save(update_fields=["published_version"])
        disabled = self.client.post(f"{self.url}/configure_warehouse_sync/", {"enabled": False, "interval_minutes": 15})
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"
        row.refresh_from_db()
        assert not row.enabled
        assert row.published_version == 2
        self.schedule.assert_called_once()

    def test_flag_and_project_boundaries_prevent_enrollment(self) -> None:
        self.flag.return_value = False
        assert self.client.get(f"{self.url}/warehouse_sync/").status_code == 404
        assert (
            self.client.post(
                f"{self.url}/configure_warehouse_sync/", {"enabled": True, "interval_minutes": 60}
            ).status_code
            == 404
        )
        self.flag.return_value = True
        other_team = Team.objects.create(organization=self.organization)
        other_table = DataWarehouseTable.objects.create(
            team=other_team, name="other_orders", format="Delta", url_pattern="s3://example-bucket/orders"
        )
        assert (
            self.client.post(
                f"/api/projects/{self.team.id}/warehouse_tables/{other_table.id}/configure_warehouse_sync/",
                {"enabled": True, "interval_minutes": 60},
            ).status_code
            == 404
        )
        assert not ManagedWarehouseExternalTable.objects.for_team(self.team.id).exists()
        self.schedule.assert_not_called()

    def test_unsupported_tables_and_invalid_intervals_do_not_start_sync(self) -> None:
        assert (
            self.client.post(
                f"{self.url}/configure_warehouse_sync/", {"enabled": True, "interval_minutes": 4}
            ).status_code
            == 400
        )
        self.table.format = "Parquet"
        self.table.save(update_fields=["format"])
        unavailable = self.client.get(f"{self.url}/warehouse_sync/")
        assert unavailable.json()["available"] is False
        assert (
            self.client.post(
                f"{self.url}/configure_warehouse_sync/", {"enabled": True, "interval_minutes": 60}
            ).status_code
            == 400
        )
        self.schedule.assert_not_called()

    def test_schedule_failure_is_safe_and_retryable(self) -> None:
        self.schedule.side_effect = RuntimeError("private transport detail")
        failed = self.client.post(f"{self.url}/configure_warehouse_sync/", {"enabled": True, "interval_minutes": 60})
        assert failed.status_code == 503
        assert "private" not in str(failed.json())
        settings = self.client.get(f"{self.url}/warehouse_sync/").json()
        assert settings["status"] == "error"
        self.schedule.side_effect = None
        retried = self.client.post(f"{self.url}/configure_warehouse_sync/", {"enabled": True, "interval_minutes": 60})
        assert retried.status_code == 200
        self.schedule.assert_called_with(self.team.id, self.table.id, 60, trigger=True)

    def test_delete_disables_the_refresh_schedule_gate(self) -> None:
        assert (
            self.client.post(
                f"{self.url}/configure_warehouse_sync/", {"enabled": True, "interval_minutes": 60}
            ).status_code
            == 200
        )
        assert self.client.delete(f"{self.url}/").status_code == 204
        assert not ManagedWarehouseExternalTable.objects.for_team(self.team.id).get(table_id=self.table.id).enabled
