from collections.abc import Collection, Iterable, Mapping
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

from products.warehouse_sources.backend.migration.capabilities import source_capabilities
from products.warehouse_sources.backend.migration.fivetran.client import FivetranClient, FivetranCredentials
from products.warehouse_sources.backend.migration.fivetran.planner import (
    CatalogLookup,
    PlannedItem,
    TableMatchLike,
    plan_items,
)
from products.warehouse_sources.backend.migration.fivetran.snapshot import fetch_snapshot
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.types import ExternalDataSourceType

# A refresh must not touch an item that an apply has claimed or finished.
_KEEP_ON_REFRESH = (
    WarehouseMigrationItem.Status.APPLYING,
    WarehouseMigrationItem.Status.APPLIED,
    WarehouseMigrationItem.Status.SKIPPED,
)
_AUTH_FAILED_MESSAGE = (
    "Fivetran rejected the API key. Check that the key is active and can read connections and destinations."
)
_CRAWL_FAILED_MESSAGE = "Reading the Fivetran account failed. Try again."


class _NoCatalog:
    """Matches nothing, so every connection reports as unsupported until the Fivetran catalog lands."""

    def match_source(self, provider: str, vendor_service: str) -> None:
        return None

    def match_destination(self, provider: str, vendor_service: str) -> None:
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


PENDING_CATALOG: CatalogLookup = _NoCatalog()


def crawl_migration(*, team_id: int, migration_id: UUID, catalog: CatalogLookup = PENDING_CATALOG) -> int:
    """Read the vendor account, plan every connection, and store the result. Returns the item count.

    A failure leaves the migration `crawling`: the workflow retries, then calls `mark_migration_failed`.
    """
    migration = WarehouseMigration.objects.for_team(team_id).filter(id=migration_id).first()
    if migration is None:
        # Deleted while the crawl waited to start.
        return 0
    migration.status = WarehouseMigration.Status.CRAWLING
    migration.latest_error = ""
    migration.save(update_fields=["status", "latest_error", "updated_at"])

    snapshot = fetch_snapshot(FivetranClient(FivetranCredentials(**migration.credentials)))
    team = Team.objects.only("organization_id").get(id=team_id)
    planned = plan_items(snapshot, catalog, source_capabilities, flag_enabled=lambda flag: _team_has_flag(team, flag))
    with transaction.atomic():
        locked = WarehouseMigration.objects.for_team(team_id).select_for_update().filter(id=migration_id).first()
        if locked is None or locked.status != WarehouseMigration.Status.CRAWLING:
            # Deleted, or a newer crawl or a failure mark already won.
            return 0
        _save_items(locked, planned)
        locked.snapshot = snapshot.to_json()
        locked.account_name = snapshot.account_name or ""
        locked.crawled_at = timezone.now()
        locked.status = WarehouseMigration.Status.READY
        locked.save(update_fields=["snapshot", "account_name", "crawled_at", "status", "updated_at"])
    return len(planned)


def _team_has_flag(team: Team, flag: str) -> bool:
    organization_id = str(team.organization_id)
    return feature_enabled_or_false(
        flag,
        organization_id,
        groups={"organization": organization_id, "project": str(team.id)},
        group_properties={"organization": {"id": organization_id}},
    )


def mark_migration_failed(*, team_id: int, migration_id: UUID, auth_failed: bool) -> None:
    WarehouseMigration.objects.for_team(team_id).filter(
        id=migration_id, status__in=(WarehouseMigration.Status.PENDING, WarehouseMigration.Status.CRAWLING)
    ).update(
        status=WarehouseMigration.Status.FAILED,
        latest_error=_AUTH_FAILED_MESSAGE if auth_failed else _CRAWL_FAILED_MESSAGE,
        updated_at=timezone.now(),
    )


def _save_items(migration: WarehouseMigration, planned: tuple[PlannedItem, ...]) -> None:
    items = WarehouseMigrationItem.objects.for_team(migration.team_id).filter(migration=migration)
    # Locked so an apply cannot claim an item between this read and the save below.
    existing = {item.vendor_connection_id: item for item in items.select_for_update()}

    for plan in planned:
        item = existing.get(plan.vendor_connection_id)
        if item is not None and item.status in _KEEP_ON_REFRESH:
            continue
        if item is None:
            item = WarehouseMigrationItem(
                team_id=migration.team_id,
                created_by_id=migration.created_by_id,
                migration=migration,
                vendor_connection_id=plan.vendor_connection_id,
            )
        item.vendor_service = plan.vendor_service
        item.name = plan.name
        item.verdict = plan.verdict
        item.caveats = list(plan.caveats)
        item.proposal = plan.proposal.to_json() if plan.proposal else None
        item.status = WarehouseMigrationItem.Status.PENDING
        item.error = ""
        item.save()

    planned_ids = {plan.vendor_connection_id for plan in planned}
    items.exclude(vendor_connection_id__in=planned_ids).exclude(status__in=_KEEP_ON_REFRESH).delete()
