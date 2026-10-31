"""Fivetran migration import, for the warehouse presentation endpoints."""

from collections.abc import Sequence
from uuid import UUID

from django.db.models import QuerySet

from pydantic import ValidationError

from products.warehouse_sources.backend.facade import contracts
from products.warehouse_sources.backend.migration import service
from products.warehouse_sources.backend.migration.flags import is_migration_import_enabled
from products.warehouse_sources.backend.migration.types import ItemProposal
from products.warehouse_sources.backend.models.warehouse_migration import (
    WarehouseMigration as _WarehouseMigration,
    WarehouseMigrationItem as _WarehouseMigrationItem,
)

PROVIDER_CHOICES = _WarehouseMigration.Provider.choices
STATUS_CHOICES = _WarehouseMigration.Status.choices
ITEM_VERDICT_CHOICES = _WarehouseMigrationItem.Verdict.choices
ITEM_STATUS_CHOICES = _WarehouseMigrationItem.Status.choices


def _to_migration(migration: _WarehouseMigration) -> contracts.WarehouseMigration:
    return contracts.WarehouseMigration(
        id=migration.id,
        provider=migration.provider,
        status=migration.status,
        account_name=migration.account_name,
        crawled_at=migration.crawled_at,
        latest_error=migration.latest_error,
        created_at=migration.created_at,
        item_counts=contracts.WarehouseMigrationItemCounts(**service.item_counts(migration)),
    )


_STALE_PLAN_CAVEAT = "The stored plan for this connection is out of date. Refresh the migration to plan it again."


def _to_item(item: _WarehouseMigrationItem) -> contracts.WarehouseMigrationItem:
    caveats = list(item.caveats)
    proposal = item.proposal
    if proposal is not None:
        # A plan stored before a field existed gets that field's default, so the API never fails on it.
        try:
            proposal = ItemProposal.from_json(proposal).to_json()
        except ValidationError:
            proposal = None
            caveats.append(_STALE_PLAN_CAVEAT)
    return contracts.WarehouseMigrationItem(
        id=item.id,
        migration_id=item.migration_id,
        vendor_connection_id=item.vendor_connection_id,
        vendor_service=item.vendor_service,
        name=item.name,
        verdict=item.verdict,
        caveats=caveats,
        proposal=proposal,
        status=item.status,
        external_data_source_id=item.external_data_source_id,
        error=item.error,
    )


def _migrations(team_id: int) -> QuerySet[_WarehouseMigration]:
    # The snapshot can be large and no endpoint returns it.
    return _WarehouseMigration.objects.for_team(team_id).defer("snapshot")


def list_migrations(team_id: int, *, limit: int, offset: int) -> tuple[list[contracts.WarehouseMigration], int]:
    """One page of the team's migrations, newest first, and the total count."""
    migrations = _migrations(team_id)
    page = migrations.order_by("-created_at", "-id")[offset : offset + limit]
    return [_to_migration(migration) for migration in page], migrations.count()


def get_migration(team_id: int, migration_id: UUID) -> contracts.WarehouseMigration | None:
    migration = _migrations(team_id).filter(id=migration_id).first()
    return _to_migration(migration) if migration else None


def create_migration(
    *, team_id: int, user_id: int, provider: str, api_key: str, api_secret: str
) -> contracts.WarehouseMigration:
    """Raises `WarehouseMigrationKeyRejectedError` or `WarehouseMigrationVendorUnreachableError`."""
    return _to_migration(
        service.create_migration(
            team_id=team_id, user_id=user_id, provider=provider, api_key=api_key, api_secret=api_secret
        )
    )


def delete_migration(team_id: int, migration_id: UUID) -> bool:
    deleted, _ = _WarehouseMigration.objects.for_team(team_id).filter(id=migration_id).delete()
    return bool(deleted)


def refresh_migration(team_id: int, migration_id: UUID) -> contracts.WarehouseMigration | None:
    """Raises `WarehouseMigrationBusyError` while a crawl runs."""
    migration = service.refresh_migration(team_id=team_id, migration_id=migration_id)
    return _to_migration(migration) if migration else None


def list_migration_items(team_id: int, migration_id: UUID) -> list[contracts.WarehouseMigrationItem] | None:
    if not _migrations(team_id).filter(id=migration_id).exists():
        return None
    items = _WarehouseMigrationItem.objects.for_team(team_id).filter(migration_id=migration_id)
    return [_to_item(item) for item in items.order_by("verdict", "name")]


def skip_migration_items(
    team_id: int,
    migration_id: UUID,
    *,
    item_ids: Sequence[UUID] | None = None,
    keep_item_ids: Sequence[UUID] | None = None,
) -> contracts.WarehouseMigrationBulkSkip | None:
    """Skip `item_ids`, or every item except `keep_item_ids`. Returns None when the migration is not found."""
    if not _migrations(team_id).filter(id=migration_id).exists():
        return None
    return service.skip_items(
        team_id=team_id, migration_id=migration_id, item_ids=item_ids, keep_item_ids=keep_item_ids
    )


def skip_migration_item(team_id: int, migration_id: UUID, item_id: UUID) -> contracts.WarehouseMigrationItem | None:
    """Raises `WarehouseMigrationItemClaimedError` once an apply claimed the item."""
    item = service.skip_item(team_id=team_id, migration_id=migration_id, item_id=item_id)
    return _to_item(item) if item else None


__all__ = [
    "ITEM_STATUS_CHOICES",
    "ITEM_VERDICT_CHOICES",
    "PROVIDER_CHOICES",
    "STATUS_CHOICES",
    "create_migration",
    "delete_migration",
    "get_migration",
    "is_migration_import_enabled",
    "list_migration_items",
    "list_migrations",
    "refresh_migration",
    "skip_migration_item",
    "skip_migration_items",
]
