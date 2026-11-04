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
    with_unique_prefixes,
)
from products.warehouse_sources.backend.migration.fivetran.snapshot import fetch_snapshot
from products.warehouse_sources.backend.migration.types import VendorSnapshot
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.types import ExternalDataSourceType

# A refresh must not touch an item that an apply has claimed or finished.
_KEEP_ON_REFRESH = (
    WarehouseMigrationItem.Status.APPLYING,
    WarehouseMigrationItem.Status.APPLIED,
    WarehouseMigrationItem.Status.SKIPPED,
)
_REPLANNED_FIELDS = ("vendor_service", "name", "verdict", "caveats", "proposal", "status", "error")
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
    with transaction.atomic():
        locked = WarehouseMigration.objects.for_team(team_id).select_for_update().filter(id=migration_id).first()
        if locked is None or locked.status != WarehouseMigration.Status.CRAWLING:
            # Deleted, or a newer crawl or a failure mark already won.
            return 0
        return len(save_plan(locked, snapshot, catalog=catalog))


def save_plan(
    migration: WarehouseMigration,
    snapshot: VendorSnapshot,
    *,
    catalog: CatalogLookup = PENDING_CATALOG,
    connection_ids: Collection[str] | None = None,
) -> tuple[PlannedItem, ...]:
    """Plan the snapshot and store it with its items. The caller holds the migration row lock.

    Without `connection_ids` the plan replaces every item. With them, only those connections are planned
    again, and no item is deleted. Either way, items an apply claimed or finished, or the user skipped, stay.
    """
    team = Team.objects.only("organization_id").get(id=migration.team_id)
    planned = plan_items(snapshot, catalog, source_capabilities, flag_enabled=lambda flag: _team_has_flag(team, flag))
    if connection_ids is not None:
        planned = tuple(plan for plan in planned if plan.vendor_connection_id in connection_ids)
    _save_items(migration, planned, delete_missing=connection_ids is None)
    migration.snapshot = snapshot.to_json()
    migration.account_name = snapshot.account_name or ""
    migration.crawled_at = timezone.now()
    migration.status = WarehouseMigration.Status.READY
    migration.save(update_fields=["snapshot", "account_name", "crawled_at", "status", "updated_at"])
    return planned


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


def _save_items(migration: WarehouseMigration, planned: tuple[PlannedItem, ...], *, delete_missing: bool) -> None:
    items = WarehouseMigrationItem.objects.for_team(migration.team_id).filter(migration=migration)
    planned_ids = {plan.vendor_connection_id for plan in planned}
    # Without deletes, only the planned items are read, so a small upload stays small on a large migration.
    touched = items if delete_missing else items.filter(vendor_connection_id__in=planned_ids)
    # Locked so an apply cannot claim an item between this read and the save below.
    existing = {item.vendor_connection_id: item for item in touched.select_for_update()}
    # Kept items keep their sources, so a refreshed connection must not reuse one of their prefixes. Read from all
    # items, because an upload locks only its own batch.
    reserved = {
        (ExternalDataSourceType(proposal["source_type"]), proposal["prefix"])
        for proposal in items.filter(status__in=_KEEP_ON_REFRESH, proposal__isnull=False).values_list(
            "proposal", flat=True
        )
    }
    planned = with_unique_prefixes(planned, reserved)

    for plan in planned:
        item = existing.get(plan.vendor_connection_id)
        if item is not None and item.status in _KEEP_ON_REFRESH:
            continue
        is_new = item is None
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
        item.save(update_fields=None if is_new else [*_REPLANNED_FIELDS, "updated_at"])

    if not delete_missing:
        return
    items.exclude(vendor_connection_id__in=planned_ids).exclude(status__in=_KEEP_ON_REFRESH).delete()
