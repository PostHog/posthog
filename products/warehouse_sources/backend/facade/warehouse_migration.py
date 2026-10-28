"""Fivetran migration import, for the warehouse presentation endpoints."""

import dataclasses
from collections.abc import Mapping, Sequence
from datetime import timedelta
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils import timezone

from pydantic import ValidationError

from products.warehouse_sources.backend.facade import contracts
from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.migration import service
from products.warehouse_sources.backend.migration.apply import (
    TableOverride,
    TableOverrideError,
    build_planned_schemas,
    with_table_overrides,
)
from products.warehouse_sources.backend.migration.flags import is_migration_import_enabled
from products.warehouse_sources.backend.migration.types import ItemProposal
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource as _ExternalDataSource
from products.warehouse_sources.backend.models.warehouse_migration import (
    WarehouseMigration as _WarehouseMigration,
    WarehouseMigrationItem as _WarehouseMigrationItem,
)

# An apply that held an item this long died before it finished, so another one may take over.
_APPLY_LEASE = timedelta(minutes=15)

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


def _to_item(item: _WarehouseMigrationItem) -> contracts.WarehouseMigrationItem:
    return contracts.WarehouseMigrationItem(
        id=item.id,
        migration_id=item.migration_id,
        vendor_connection_id=item.vendor_connection_id,
        vendor_service=item.vendor_service,
        name=item.name,
        verdict=item.verdict,
        caveats=list(item.caveats),
        proposal=item.proposal,
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


def skip_migration_item(team_id: int, migration_id: UUID, item_id: UUID) -> contracts.WarehouseMigrationItem | None:
    """Raises `WarehouseMigrationItemClaimedError` once an apply claimed the item."""
    item = service.skip_item(team_id=team_id, migration_id=migration_id, item_id=item_id)
    return _to_item(item) if item else None


def find_migration_item(team_id: int, item_id: UUID) -> contracts.WarehouseMigrationItem | None:
    item = _WarehouseMigrationItem.objects.for_team(team_id).filter(id=item_id).first()
    return _to_item(item) if item else None


def claim_migration_item(
    team_id: int,
    item_id: UUID,
    *,
    prefix_override: str | None = None,
    table_overrides: Sequence[contracts.MigrationTableOverride] = (),
) -> contracts.ClaimedWarehouseMigrationItem | None:
    """Mark the item as being applied. Returns None when it is unsupported, done, skipped, or claimed.

    When an earlier attempt created the source and then failed or died, the claim links that source and
    applies the item, and returns it in `recovered_source_id` instead of letting the caller create another.
    Raises `WarehouseMigrationTableOverrideError` when the table overrides do not fit the plan.
    """
    items = _WarehouseMigrationItem.objects.for_team(team_id).filter(id=item_id, proposal__isnull=False)
    item = items.first()
    if item is None:
        return None
    now = timezone.now()
    # Conditional, so two requests for one item cannot both create a source.
    claimable = Q(status__in=(_WarehouseMigrationItem.Status.PENDING, _WarehouseMigrationItem.Status.FAILED)) | Q(
        status=_WarehouseMigrationItem.Status.APPLYING, updated_at__lt=now - _APPLY_LEASE
    )
    try:
        proposal = ItemProposal.from_json(item.proposal or {})
    except ValidationError:
        # Only a claimable item: an applied one failed here would be reset by a refresh and applied twice.
        items.filter(claimable).update(
            status=_WarehouseMigrationItem.Status.FAILED,
            error="The stored plan for this connection is not valid. Refresh the migration.",
            updated_at=now,
        )
        return None
    try:
        proposal = with_table_overrides(
            proposal,
            [TableOverride(vendor_table=o.vendor_table, posthog_table=o.posthog_table) for o in table_overrides],
        )
    except TableOverrideError as error:
        raise contracts.WarehouseMigrationTableOverrideError(str(error)) from error
    prefix = (proposal.prefix if prefix_override is None else prefix_override) or None
    if not items.filter(claimable).update(
        status=_WarehouseMigrationItem.Status.APPLYING, updated_at=now, claimed_at=now, claimed_prefix=prefix
    ):
        return None
    claimed = contracts.ClaimedWarehouseMigrationItem(
        id=item.id,
        migration_id=item.migration_id,
        name=item.name,
        caveats=list(item.caveats),
        source_type=proposal.source_type,
        prefix=prefix,
        description=_source_description(item),
        sync_frequency=proposal.sync_frequency,
        start_paused=proposal.start_paused,
        proposal=proposal.to_json(),
    )
    # `item` still holds the previous claim, which is the attempt that may have left a source behind.
    leftover = _source_created_since_claim(item, proposal.source_type)
    if leftover is None:
        return claimed
    caveats = [*item.caveats, _LEFTOVER_CAVEAT]
    finish_migration_item(team_id, item.id, source_id=leftover, caveats=caveats)
    return dataclasses.replace(claimed, caveats=caveats, recovered_source_id=leftover)


_LEFTOVER_CAVEAT = "An earlier attempt created this source but did not finish. Check its tables and sync schedule."


def _source_description(item: _WarehouseMigrationItem) -> str:
    return f"Imported from the migrated connection {item.name}."


def _source_created_since_claim(item: _WarehouseMigrationItem, source_type: str) -> UUID | None:
    """The source an apply of this item created after its claim, if one exists. Apply is its only creator:
    the type, prefix and description match it, and the claim time rules out older sources."""
    if item.claimed_at is None:
        return None
    sources = _ExternalDataSource.objects.filter(
        team_id=item.team_id,
        source_type=source_type,
        description=_source_description(item),
        created_at__gte=item.claimed_at,
    ).exclude(deleted=True)
    if item.claimed_prefix:
        sources = sources.filter(prefix=item.claimed_prefix)
    else:
        sources = sources.filter(Q(prefix__isnull=True) | Q(prefix=""))
    return sources.order_by("created_at").values_list("id", flat=True).first()


def plan_migration_schemas(
    proposal: Mapping, source_schemas: list[SourceSchema], permission_errors: Mapping[str, str | None]
) -> contracts.PlannedMigrationSchemas:
    planned = build_planned_schemas(ItemProposal.from_json(proposal), source_schemas, permission_errors)
    return contracts.PlannedMigrationSchemas(
        schemas=planned.schemas,
        unavailable=list(planned.unavailable),
        webhook_only=list(planned.webhook_only),
        planned=list(planned.planned),
    )


def finish_migration_item(team_id: int, item_id: UUID, *, source_id: UUID, caveats: list[str]) -> None:
    _WarehouseMigrationItem.objects.for_team(team_id).filter(id=item_id).update(
        status=_WarehouseMigrationItem.Status.APPLIED,
        external_data_source_id=source_id,
        caveats=caveats,
        error="",
        updated_at=timezone.now(),
    )


def fail_migration_item(team_id: int, item_id: UUID, error: str) -> None:
    """Mark the item failed, unless the attempt created the source before it failed: then link it."""
    item = _WarehouseMigrationItem.objects.for_team(team_id).filter(id=item_id).first()
    if item is None:
        return
    try:
        source_type = ItemProposal.from_json(item.proposal or {}).source_type
    except ValidationError:
        source_type = None
    leftover = _source_created_since_claim(item, source_type) if source_type else None
    if leftover is not None:
        caveat = (
            f"Creating the source failed partway ({error}). The source exists, so check its tables and sync schedule."
        )
        finish_migration_item(team_id, item_id, source_id=leftover, caveats=[*item.caveats, caveat])
        return
    _WarehouseMigrationItem.objects.for_team(team_id).filter(id=item_id).update(
        status=_WarehouseMigrationItem.Status.FAILED, error=error, updated_at=timezone.now()
    )


__all__ = [
    "ITEM_STATUS_CHOICES",
    "ITEM_VERDICT_CHOICES",
    "claim_migration_item",
    "fail_migration_item",
    "find_migration_item",
    "finish_migration_item",
    "plan_migration_schemas",
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
]
