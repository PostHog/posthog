import dataclasses
from collections.abc import Collection
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

from products.warehouse_sources.backend.migration import catalog as migration_catalog
from products.warehouse_sources.backend.migration.capabilities import source_capabilities
from products.warehouse_sources.backend.migration.fivetran.client import FivetranClient, FivetranCredentials
from products.warehouse_sources.backend.migration.fivetran.planner import (
    CatalogLookup,
    PlannedItem,
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


def crawl_migration(
    *, team_id: int, migration_id: UUID, workflow_id: str, catalog: CatalogLookup = migration_catalog
) -> int:
    """Read the vendor account, plan every connection, and store the result. Returns the item count.

    Writes only while the migration still names `workflow_id` as its crawl, so a replaced crawl changes nothing.
    A failure leaves the migration `crawling`: the workflow retries, then calls `mark_migration_failed`.
    """
    own = WarehouseMigration.objects.for_team(team_id).filter(id=migration_id, workflow_id=workflow_id)
    if not own.update(status=WarehouseMigration.Status.CRAWLING, latest_error="", updated_at=timezone.now()):
        # Deleted, or a newer crawl replaced this one.
        return 0
    migration = own.first()
    if migration is None:
        return 0

    snapshot = fetch_snapshot(FivetranClient(FivetranCredentials(**migration.credentials)))
    with transaction.atomic():
        locked = own.select_for_update().first()
        if locked is None or locked.status != WarehouseMigration.Status.CRAWLING:
            # Deleted, replaced by a newer crawl, or already marked failed.
            return 0
        return len(save_plan(locked, snapshot, catalog=catalog))


def save_plan(
    migration: WarehouseMigration,
    snapshot: VendorSnapshot,
    *,
    catalog: CatalogLookup = migration_catalog,
    connection_ids: Collection[str] | None = None,
) -> tuple[PlannedItem, ...]:
    """Plan the snapshot and store it with its items. The caller holds the migration row lock.

    Without `connection_ids` the plan replaces every item. With them, only those connections are planned
    again, and no item is deleted. Either way, items an apply claimed or finished, or the user skipped, stay.
    """
    team = Team.objects.only("organization_id").get(id=migration.team_id)
    to_plan = snapshot
    if connection_ids is not None:
        # Only the batch is planned. `_save_items` reserves the prefixes of every other item.
        batch = set(connection_ids)
        to_plan = dataclasses.replace(
            snapshot, connections=tuple(connection for connection in snapshot.connections if connection.id in batch)
        )
    planned = plan_items(to_plan, catalog, source_capabilities, flag_enabled=lambda flag: _team_has_flag(team, flag))
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


def mark_migration_failed(*, team_id: int, migration_id: UUID, workflow_id: str, auth_failed: bool) -> None:
    """Mark the crawl `workflow_id` failed, unless a newer crawl replaced it."""
    WarehouseMigration.objects.for_team(team_id).filter(
        id=migration_id,
        workflow_id=workflow_id,
        status__in=(WarehouseMigration.Status.PENDING, WarehouseMigration.Status.CRAWLING),
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
    # Kept items keep their sources, so a refreshed connection must not reuse one of their prefixes. An upload also
    # keeps every item outside its batch, with the prefix its earlier plan gave it.
    keeps = (
        Q(status__in=_KEEP_ON_REFRESH)
        if delete_missing
        else Q(status__in=_KEEP_ON_REFRESH) | ~Q(vendor_connection_id__in=planned_ids)
    )
    reserved = {
        (ExternalDataSourceType(source_type), prefix)
        for source_type, prefix in items.filter(keeps, proposal__isnull=False).values_list(
            "proposal__source_type", "proposal__prefix"
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
