from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.warehouse_sources.backend.migration.capabilities import source_capabilities
from products.warehouse_sources.backend.migration.fivetran.client import (
    FivetranAuthError,
    FivetranClient,
    FivetranCredentials,
)
from products.warehouse_sources.backend.migration.fivetran.planner import CatalogLookup, PlannedItem, plan_items
from products.warehouse_sources.backend.migration.fivetran.snapshot import fetch_snapshot
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem

_KEEP_ON_REFRESH = (WarehouseMigrationItem.Status.APPLIED, WarehouseMigrationItem.Status.SKIPPED)


class _NoCatalog:
    """Matches nothing, so every connection reports as unsupported until the Fivetran catalog lands."""

    def match_source(self, provider: str, vendor_service: str) -> None:
        return None

    def match_destination(self, provider: str, vendor_service: str) -> None:
        return None


PENDING_CATALOG: CatalogLookup = _NoCatalog()


def crawl_migration(*, team_id: int, migration_id: UUID, catalog: CatalogLookup = PENDING_CATALOG) -> int:
    """Read the vendor account, plan every connection, and store the result. Returns the item count."""
    migration = WarehouseMigration.objects.for_team(team_id).get(id=migration_id)
    _set_status(migration, WarehouseMigration.Status.CRAWLING, error="")

    try:
        snapshot = fetch_snapshot(FivetranClient(FivetranCredentials(**migration.credentials)))
    except FivetranAuthError:
        _set_status(
            migration,
            WarehouseMigration.Status.FAILED,
            error="Fivetran rejected the API key. Check that the key is active and can read connections and destinations.",
        )
        raise
    except Exception:
        _set_status(
            migration, WarehouseMigration.Status.FAILED, error="Reading the Fivetran account failed. Try again."
        )
        raise

    planned = plan_items(snapshot, catalog, source_capabilities)
    with transaction.atomic():
        _save_items(migration, planned)
        migration.snapshot = snapshot.to_json()
        migration.account_name = snapshot.account_name or ""
        migration.crawled_at = timezone.now()
        migration.status = WarehouseMigration.Status.READY
        migration.save(update_fields=["snapshot", "account_name", "crawled_at", "status", "updated_at"])
    return len(planned)


def _set_status(migration: WarehouseMigration, status: WarehouseMigration.Status, *, error: str) -> None:
    migration.status = status
    migration.latest_error = error
    migration.save(update_fields=["status", "latest_error", "updated_at"])


def _save_items(migration: WarehouseMigration, planned: tuple[PlannedItem, ...]) -> None:
    items = WarehouseMigrationItem.objects.for_team(migration.team_id).filter(migration=migration)
    existing = {item.vendor_connection_id: item for item in items}

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
