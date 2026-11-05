from collections.abc import Callable
from uuid import UUID

from django.db import transaction
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
from products.warehouse_sources.backend.migration.fivetran.snapshot import fetch_snapshot
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

    snapshot = fetch_snapshot(FivetranClient(FivetranCredentials(**migration.credentials)))
    team = Team.objects.only("organization_id").get(id=team_id)
    planned = plan_items(
        snapshot,
        catalog,
        source_capabilities,
        flag_enabled=_flag_checker(team, migration.created_by),
        unique_prefixes=False,
    )
    with transaction.atomic():
        locked = own.select_for_update().first()
        if locked is None or locked.status != WarehouseMigration.Status.CRAWLING:
            # Deleted, replaced by a newer crawl, or already marked failed.
            return 0
        _save_items(locked, planned)
        locked.snapshot = snapshot.to_json()
        locked.account_name = snapshot.account_name or ""
        locked.crawled_at = timezone.now()
        locked.status = WarehouseMigration.Status.READY
        locked.save(update_fields=["snapshot", "account_name", "crawled_at", "status", "updated_at"])
    return len(planned)


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


def _save_items(migration: WarehouseMigration, planned: tuple[PlannedItem, ...]) -> None:
    items = WarehouseMigrationItem.objects.for_team(migration.team_id).filter(migration=migration)
    # Locked so an apply cannot claim an item between this read and the save below.
    existing = {item.vendor_connection_id: item for item in items.select_for_update()}
    kept = {connection_id for connection_id, item in existing.items() if item.status in _KEEP_ON_REFRESH}
    # A refreshed connection must not take the prefix of a source an item has or is creating.
    reserved = {
        (ExternalDataSourceType(item.proposal["source_type"]), item.proposal["prefix"])
        for item in existing.values()
        if item.status in _HAS_SOURCE and item.proposal
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

    planned_ids = {plan.vendor_connection_id for plan in planned}
    items.exclude(vendor_connection_id__in=planned_ids).exclude(status__in=_KEEP_ON_REFRESH).delete()
