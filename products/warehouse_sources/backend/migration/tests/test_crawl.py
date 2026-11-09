import uuid
from collections.abc import Collection, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import requests_mock
from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.warehouse_sources.backend.migration.catalog import TableMatch
from products.warehouse_sources.backend.migration.crawl import (
    crawl_migration,
    mark_migration_failed,
    plan_snapshot,
    save_plan,
)
from products.warehouse_sources.backend.migration.fivetran.client import FIVETRAN_API_URL, FivetranAuthError
from products.warehouse_sources.backend.migration.fivetran.snapshot import parse_connection
from products.warehouse_sources.backend.migration.types import MigrationProvider, VendorSnapshot, Verdict
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.crawl_warehouse_migration import (
    CrawlWarehouseMigrationInputs,
    CrawlWarehouseMigrationWorkflow,
    MarkWarehouseMigrationFailedInputs,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class _HubspotOnly:
    def match_source(self, provider: str, vendor_service: str) -> ExternalDataSourceType | None:
        return {"hubspot": ExternalDataSourceType.HUBSPOT, "instagram_business": ExternalDataSourceType.INSTAGRAM}.get(
            vendor_service
        )

    def match_destination(self, provider: str, vendor_service: str) -> str | None:
        return None

    def posthog_tables(self, source_type: ExternalDataSourceType) -> None:
        return None

    def match_tables(
        self, provider: str, vendor_tables: Iterable[str], posthog_table_names: Collection[str]
    ) -> tuple[TableMatch, ...]:
        return ()

    def prefill_config(
        self, provider: str, source_type: ExternalDataSourceType, vendor_config: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {}


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"json": {"code": "Success", "data": data}}


def _mock_account(
    m: requests_mock.Mocker,
    connection_ids: list[str],
    names: Mapping[str, str] | None = None,
    service: str = "hubspot",
) -> None:
    m.get(f"{FIVETRAN_API_URL}/account/info", **_ok({"account_id": "acct_example", "account_name": "Example Co"}))
    m.get(f"{FIVETRAN_API_URL}/groups", **_ok({"items": []}))
    m.get(f"{FIVETRAN_API_URL}/connections", **_ok({"items": [{"id": cid} for cid in connection_ids]}))
    for cid in connection_ids:
        m.get(
            f"{FIVETRAN_API_URL}/connections/{cid}",
            **_ok({"id": cid, "service": service, "schema": (names or {}).get(cid, cid), "sync_frequency": 360}),
        )
        m.get(f"{FIVETRAN_API_URL}/connections/{cid}/schemas", status_code=404, json={"message": "Not found"})


_CRAWL = "warehouse-migration-crawl-test"


class TestCrawlMigration(BaseTest):
    def _migration(self) -> WarehouseMigration:
        return WarehouseMigration.objects.for_team(self.team.pk).create(
            team_id=self.team.pk,
            created_by=self.user,
            provider=WarehouseMigration.Provider.FIVETRAN,
            credentials={"api_key": "fake-key", "api_secret": "fake-secret"},
            workflow_id=_CRAWL,
        )

    def _items(self, migration: WarehouseMigration) -> dict[str, WarehouseMigrationItem]:
        items = WarehouseMigrationItem.objects.for_team(self.team.pk).filter(migration=migration)
        return {item.vendor_connection_id: item for item in items}

    def _prefixes(self, migration: WarehouseMigration) -> dict[str, str]:
        return {cid: (item.proposal or {})["prefix"] for cid, item in self._items(migration).items()}

    @parameterized.expand(
        [
            ("applying", WarehouseMigrationItem.Status.APPLYING, "conn_applied_2"),
            ("applied", WarehouseMigrationItem.Status.APPLIED, "conn_applied_2"),
            # A skipped item has no source, so its prefix stays free.
            ("skipped", WarehouseMigrationItem.Status.SKIPPED, "conn_applied"),
        ]
    )
    def test_refresh_keeps_claimed_and_finished_items_and_replaces_the_rest(
        self, _name: str, kept_status: WarehouseMigrationItem.Status, new_prefix: str
    ) -> None:
        migration = self._migration()
        with requests_mock.Mocker() as m:
            _mock_account(m, ["conn_applied", "conn_pending", "conn_removed"])
            assert (
                crawl_migration(
                    team_id=self.team.pk, migration_id=migration.id, workflow_id=_CRAWL, catalog=_HubspotOnly()
                )
                == 3
            )

        items = self._items(migration)
        applied = items["conn_applied"]
        applied.status = kept_status
        applied.caveats = ["kept from the first crawl"]
        applied.save(update_fields=["status", "caveats"])

        with requests_mock.Mocker() as m:
            # The kept connection was renamed in Fivetran, and the new one took its old name.
            _mock_account(
                m,
                ["conn_applied", "conn_pending", "conn_new"],
                names={"conn_applied": "renamed", "conn_new": "conn_applied"},
            )
            crawl_migration(team_id=self.team.pk, migration_id=migration.id, workflow_id=_CRAWL, catalog=_HubspotOnly())

        migration.refresh_from_db()
        items = self._items(migration)
        assert migration.status == WarehouseMigration.Status.READY
        assert migration.account_name == "Example Co"
        assert set(items) == {"conn_applied", "conn_pending", "conn_new"}
        assert (items["conn_applied"].status, items["conn_applied"].caveats) == (
            kept_status,
            ["kept from the first crawl"],
        )
        assert items["conn_new"].verdict == Verdict.CAVEATS
        assert items["conn_new"].proposal is not None
        assert items["conn_new"].proposal["source_type"] == ExternalDataSourceType.HUBSPOT
        assert items["conn_new"].proposal["prefix"] == new_prefix

    def test_a_partial_upload_keeps_prefixes_unique_against_items_outside_its_batch(self) -> None:
        migration = self._migration()

        def snapshot(names: dict[str, str]) -> VendorSnapshot:
            return VendorSnapshot(
                provider=MigrationProvider.FIVETRAN,
                account_id="acct_example",
                account_name=None,
                destinations=(),
                connections=tuple(
                    parse_connection({"id": cid, "service": "hubspot", "schema": name}, None, utc_offset_hours=0)
                    for cid, name in names.items()
                ),
            )

        first = snapshot({"conn_a": "shared", "conn_b": "shared"})
        save_plan(migration, first, plan_snapshot(migration, first, catalog=_HubspotOnly()))
        assert self._prefixes(migration) == {
            "conn_a": "shared",
            "conn_b": "shared_2",
        }

        # Planned whole, conn_b would now get `shared`, but only conn_a is saved.
        second = snapshot({"conn_a": "shared_2", "conn_b": "shared"})
        planned = plan_snapshot(migration, second, catalog=_HubspotOnly(), connection_ids=["conn_a"])
        save_plan(migration, second, planned, replace_all=False)

        prefixes = self._prefixes(migration)
        assert prefixes["conn_b"] == "shared_2"
        assert prefixes["conn_a"] != "shared_2"

    @parameterized.expand([("auth_message", True, "rejected the API key"), ("generic_message", False, "Try again")])
    def test_failed_crawl_is_marked_failed_once_retries_run_out(
        self, _name: str, auth_failed: bool, expected_error: str
    ) -> None:
        migration = self._migration()
        with requests_mock.Mocker() as m:
            m.get(f"{FIVETRAN_API_URL}/account/info", status_code=401, json={"message": "Unauthorized"})
            with pytest.raises(FivetranAuthError):
                crawl_migration(
                    team_id=self.team.pk, migration_id=migration.id, workflow_id=_CRAWL, catalog=_HubspotOnly()
                )
        migration.refresh_from_db()
        # Temporal may still retry, so the attempt itself does not mark the migration failed.
        assert migration.status == WarehouseMigration.Status.CRAWLING

        mark_migration_failed(
            team_id=self.team.pk, migration_id=migration.id, workflow_id=_CRAWL, auth_failed=auth_failed
        )

        migration.refresh_from_db()
        assert migration.status == WarehouseMigration.Status.FAILED
        assert expected_error in migration.latest_error

    @patch("products.warehouse_sources.backend.migration.crawl.posthog_feature_flag_enabled", return_value=False)
    def test_source_flags_are_checked_once_for_the_user_who_started_the_migration(
        self, flag_enabled: MagicMock
    ) -> None:
        migration = self._migration()
        with requests_mock.Mocker() as m:
            _mock_account(m, ["conn_a", "conn_b"], service="instagram_business")
            crawl_migration(team_id=self.team.pk, migration_id=migration.id, workflow_id=_CRAWL, catalog=_HubspotOnly())

        flag_enabled.assert_called_once_with(
            "dwh-instagram", str(self.user.distinct_id), organization_id=self.team.organization_id, team_id=self.team.pk
        )
        assert {item.verdict for item in self._items(migration).values()} == {Verdict.UNSUPPORTED}

    def test_the_default_catalog_plans_known_connectors(self) -> None:
        migration = self._migration()
        with requests_mock.Mocker() as m:
            _mock_account(m, ["conn_hubspot"])
            crawl_migration(team_id=self.team.pk, migration_id=migration.id, workflow_id=_CRAWL)

        item = self._items(migration)["conn_hubspot"]
        assert item.proposal is not None
        assert item.proposal["source_type"] == ExternalDataSourceType.HUBSPOT

    def test_a_deleted_migration_stops_reading_fivetran(self) -> None:
        migration = self._migration()

        def delete_while_reading(request: Any, context: Any) -> dict[str, Any]:
            WarehouseMigration.objects.for_team(self.team.pk).filter(id=migration.id).delete()
            return {"code": "Success", "data": {"id": "conn_a", "service": "hubspot", "schema": "conn_a"}}

        with requests_mock.Mocker() as m:
            _mock_account(m, ["conn_a", "conn_b"])
            m.get(f"{FIVETRAN_API_URL}/connections/conn_a", json=delete_while_reading)
            assert (
                crawl_migration(
                    team_id=self.team.pk, migration_id=migration.id, workflow_id=_CRAWL, catalog=_HubspotOnly()
                )
                == 0
            )

        assert "/v1/connections/conn_b" not in {request.path for request in m.request_history}

    def test_a_replaced_crawl_changes_nothing(self) -> None:
        migration = self._migration()
        with requests_mock.Mocker() as m:
            m.get(f"{FIVETRAN_API_URL}/account/info", status_code=401, json={"message": "Unauthorized"})
            with pytest.raises(FivetranAuthError):
                crawl_migration(
                    team_id=self.team.pk, migration_id=migration.id, workflow_id=_CRAWL, catalog=_HubspotOnly()
                )
        # A refresh hands the migration to a new crawl while the old one's failure mark is still in flight.
        WarehouseMigration.objects.for_team(self.team.pk).filter(id=migration.id).update(
            workflow_id="crawl-2", status=WarehouseMigration.Status.CRAWLING
        )

        mark_migration_failed(team_id=self.team.pk, migration_id=migration.id, workflow_id=_CRAWL, auth_failed=True)
        with requests_mock.Mocker() as m:
            _mock_account(m, ["conn_old"])
            assert (
                crawl_migration(
                    team_id=self.team.pk, migration_id=migration.id, workflow_id=_CRAWL, catalog=_HubspotOnly()
                )
                == 0
            )

        migration.refresh_from_db()
        assert (migration.status, migration.latest_error) == (WarehouseMigration.Status.CRAWLING, "")
        assert self._items(migration) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, expected_attempts, auth_failed",
    [(FivetranAuthError(401, "Unauthorized"), 1, True), (RuntimeError("Fivetran timed out"), 3, False)],
)
async def test_workflow_marks_the_migration_failed_once_retries_run_out(
    error: Exception, expected_attempts: int, auth_failed: bool
) -> None:
    attempts: list[int] = []
    marked: list[MarkWarehouseMigrationFailedInputs] = []

    @activity.defn(name="crawl_warehouse_migration_activity")
    def crawl(inputs: CrawlWarehouseMigrationInputs) -> int:
        attempts.append(activity.info().attempt)
        raise error

    @activity.defn(name="mark_warehouse_migration_failed_activity")
    def mark_failed(inputs: MarkWarehouseMigrationFailedInputs) -> None:
        marked.append(inputs)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-warehouse-migration-crawl",
            workflows=[CrawlWarehouseMigrationWorkflow],
            activities=[crawl, mark_failed],
            workflow_runner=UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=2),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    CrawlWarehouseMigrationWorkflow.run,
                    CrawlWarehouseMigrationInputs(team_id=1, migration_id=uuid.uuid4()),
                    id=str(uuid.uuid4()),
                    task_queue="test-warehouse-migration-crawl",
                )

    assert len(attempts) == expected_attempts
    assert [inputs.auth_failed for inputs in marked] == [auth_failed]
