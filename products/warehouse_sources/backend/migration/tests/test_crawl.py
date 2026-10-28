import uuid
from collections.abc import Collection, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from posthog.test.base import BaseTest

import requests_mock
from parameterized import parameterized
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.warehouse_sources.backend.migration.crawl import crawl_migration, mark_migration_failed
from products.warehouse_sources.backend.migration.fivetran.client import FIVETRAN_API_URL, FivetranAuthError
from products.warehouse_sources.backend.migration.fivetran.planner import TableMatchLike
from products.warehouse_sources.backend.migration.types import Verdict
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.crawl_warehouse_migration import (
    CrawlWarehouseMigrationInputs,
    CrawlWarehouseMigrationWorkflow,
    MarkWarehouseMigrationFailedInputs,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class _HubspotOnly:
    def match_source(self, provider: str, vendor_service: str) -> ExternalDataSourceType | None:
        return ExternalDataSourceType.HUBSPOT if vendor_service == "hubspot" else None

    def match_destination(self, provider: str, vendor_service: str) -> str | None:
        return None

    def posthog_tables(self, source_type: ExternalDataSourceType) -> None:
        return None

    def match_tables(
        self, provider: str, vendor_tables: Iterable[str], posthog_table_names: Collection[str]
    ) -> tuple[TableMatchLike, ...]:
        return ()

    def prefill_config(
        self, provider: str, source_type: ExternalDataSourceType, vendor_config: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {}


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

    @parameterized.expand(
        [
            ("applying", WarehouseMigrationItem.Status.APPLYING),
            ("applied", WarehouseMigrationItem.Status.APPLIED),
            ("skipped", WarehouseMigrationItem.Status.SKIPPED),
        ]
    )
    def test_refresh_keeps_claimed_and_finished_items_and_replaces_the_rest(
        self, _name: str, kept_status: WarehouseMigrationItem.Status
    ) -> None:
        migration = self._migration()
        with requests_mock.Mocker() as m:
            _mock_account(m, ["conn_applied", "conn_pending", "conn_removed"])
            assert crawl_migration(team_id=self.team.pk, migration_id=migration.id, catalog=_HubspotOnly()) == 3

        items = self._items(migration)
        applied = items["conn_applied"]
        applied.status = kept_status
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
        assert (items["conn_applied"].status, items["conn_applied"].caveats) == (
            kept_status,
            ["kept from the first crawl"],
        )
        assert items["conn_new"].verdict == Verdict.CAVEATS
        assert items["conn_new"].proposal is not None
        assert items["conn_new"].proposal["source_type"] == ExternalDataSourceType.HUBSPOT

    @parameterized.expand([("auth_failed", True, "rejected the API key"), ("other_failure", False, "Try again")])
    def test_failed_crawl_is_marked_failed_once_retries_run_out(
        self, _name: str, auth_failed: bool, expected_error: str
    ) -> None:
        migration = self._migration()
        with requests_mock.Mocker() as m:
            m.get(f"{FIVETRAN_API_URL}/account/info", status_code=401, json={"message": "Unauthorized"})
            with pytest.raises(FivetranAuthError):
                crawl_migration(team_id=self.team.pk, migration_id=migration.id, catalog=_HubspotOnly())
        migration.refresh_from_db()
        # Temporal may still retry, so the attempt itself does not mark the migration failed.
        assert migration.status == WarehouseMigration.Status.CRAWLING

        mark_migration_failed(team_id=self.team.pk, migration_id=migration.id, auth_failed=auth_failed)

        migration.refresh_from_db()
        assert migration.status == WarehouseMigration.Status.FAILED
        assert expected_error in migration.latest_error


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
