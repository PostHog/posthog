import dataclasses
from collections.abc import Callable, Collection
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from posthog.models import Team, User
from posthog.permissions import posthog_feature_flag_enabled

from products.warehouse_sources.backend.migration import catalog as migration_catalog
from products.warehouse_sources.backend.migration.capabilities import source_capabilities
from products.warehouse_sources.backend.migration.fivetran.client import FivetranClient, FivetranCredentials
from products.warehouse_sources.backend.migration.fivetran.planner import (
    CatalogLookup,
    PlannedItem,
    plan_items,
    with_unique_prefixes,
)
from products.warehouse_sources.backend.migration.fivetran.snapshot import SnapshotStoppedError, fetch_snapshot
from products.warehouse_sources.backend.migration.types import VendorSnapshot
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.types import ExternalDataSourceType

# A refresh must not touch an item that an apply has claimed or finished.
_KEEP_ON_REFRESH = (
    WarehouseMigrationItem.Status.APPLYING,
    WarehouseMigrationItem.Status.APPLIED,
    WarehouseMigrationItem.Status.SKIPPED,
)
# Kept items that have, or are creating, a PostHog source, so their prefixes are taken.
_HAS_SOURCE = (WarehouseMigrationItem.Status.APPLYING, WarehouseMigrationItem.Status.APPLIED)
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
    migration = own.select_related("created_by").first()
    if migration is None:
        return 0

    try:
        # Stops reading Fivetran once the migration is deleted or a newer crawl replaces this one.
        snapshot = fetch_snapshot(FivetranClient(FivetranCredentials(**migration.credentials)), keep_going=own.exists)
    except SnapshotStoppedError:
        return 0
    planned = plan_snapshot(migration, snapshot, catalog=catalog)
    with transaction.atomic():
        locked = own.select_for_update().first()
        if locked is None or locked.status != WarehouseMigration.Status.CRAWLING:
            # Deleted, replaced by a newer crawl, or already marked failed.
            return 0
        save_plan(locked, snapshot, planned)
    return len(planned)


def plan_snapshot(
    migration: WarehouseMigration,
    snapshot: VendorSnapshot,
    *,
    catalog: CatalogLookup = migration_catalog,
    connection_ids: Collection[str] | None = None,
) -> tuple[PlannedItem, ...]:
    """Plan the snapshot's connections, or only `connection_ids`. Prefixes are made unique when they are saved."""
    if connection_ids is not None:
        batch = set(connection_ids)
        snapshot = dataclasses.replace(
            snapshot, connections=tuple(connection for connection in snapshot.connections if connection.id in batch)
        )
    team = Team.objects.only("organization_id").get(id=migration.team_id)
    return plan_items(
        snapshot,
        catalog,
        source_capabilities,
        flag_enabled=_flag_checker(team, migration.created_by),
        unique_prefixes=False,
    )


def save_plan(
    migration: WarehouseMigration,
    snapshot: VendorSnapshot,
    planned: tuple[PlannedItem, ...],
    *,
    replace_all: bool = True,
) -> None:
    """Store the snapshot and its planned items. The caller holds the migration row lock.

    With `replace_all`, items for connections no longer planned are deleted. Without it, as for an upload, only the
    planned connections change. Either way, items an apply claimed or finished, or the user skipped, stay.
    """
    _save_items(migration, planned, delete_missing=replace_all)
    migration.snapshot = snapshot.to_json()
    migration.account_name = snapshot.account_name or ""
    migration.crawled_at = timezone.now()
    migration.status = WarehouseMigration.Status.READY
    migration.save(update_fields=["snapshot", "account_name", "crawled_at", "status", "updated_at"])


def _flag_checker(team: Team, user: User | None) -> Callable[[str], bool]:
    """Checks source flags for the user who started the migration, as the source page does for them."""
    results: dict[str, bool] = {}

    def enabled(flag: str) -> bool:
        if flag not in results:
            results[flag] = bool(user and user.distinct_id) and posthog_feature_flag_enabled(
                flag, str(user.distinct_id) if user else "", organization_id=team.organization_id, team_id=team.id
            )
        return results[flag]

    return enabled


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
    kept = {connection_id for connection_id, item in existing.items() if item.status in _KEEP_ON_REFRESH}
    # A refreshed connection must not take the prefix of a source an item has or is creating. An upload also keeps
    # each item outside its batch, except skipped ones, with the prefix its earlier plan gave it.
    taken = Q(status__in=_HAS_SOURCE)
    if not delete_missing:
        taken |= ~Q(vendor_connection_id__in=planned_ids) & ~Q(status=WarehouseMigrationItem.Status.SKIPPED)
    reserved = {
        (ExternalDataSourceType(source_type), prefix)
        for source_type, prefix in items.filter(taken, proposal__isnull=False).values_list(
            "proposal__source_type", "proposal__prefix"
        )
    }
    replanned = with_unique_prefixes([plan for plan in planned if plan.vendor_connection_id not in kept], reserved)

    for plan in replanned:
        item = existing.get(plan.vendor_connection_id)
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
