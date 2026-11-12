"""Fivetran migration import, for the warehouse presentation endpoints."""

import dataclasses
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from pydantic import ValidationError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.billing import FREE_HISTORICAL_WINDOW
from products.warehouse_sources.backend.facade import contracts
from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.migration import service
from products.warehouse_sources.backend.migration.apply import (
    TableOverride,
    TableOverrideError,
    build_planned_schemas,
    with_table_overrides,
)
from products.warehouse_sources.backend.migration.capabilities import source_capabilities
from products.warehouse_sources.backend.migration.cost import USAGE_QUERY, Confidence, ReportedUsage
from products.warehouse_sources.backend.migration.flags import is_migration_import_enabled
from products.warehouse_sources.backend.migration.types import ItemProposal, VendorSnapshot, VendorTable
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


def _to_migrations(team_id: int, migrations: list[_WarehouseMigration]) -> list[contracts.WarehouseMigration]:
    counts = service.item_counts(team_id=team_id, migration_ids=[migration.id for migration in migrations])
    return [_to_migration(migration, counts[migration.id]) for migration in migrations]


def _to_migration(migration: _WarehouseMigration, counts: dict[str, int] | None = None) -> contracts.WarehouseMigration:
    if counts is None:
        counts = service.item_counts(team_id=migration.team_id, migration_ids=[migration.id])[migration.id]
    return contracts.WarehouseMigration(
        id=migration.id,
        provider=migration.provider,
        status=migration.status,
        account_name=migration.account_name,
        crawled_at=migration.crawled_at,
        latest_error=migration.latest_error,
        created_at=migration.created_at,
        item_counts=contracts.WarehouseMigrationItemCounts(**counts),
        has_vendor_key=bool(migration.credentials),
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
        created_by=(
            contracts.WarehouseMigrationCreator(first_name=item.created_by.first_name, email=item.created_by.email)
            if item.created_by
            else None
        ),
    )


def list_migrations(team_id: int, *, limit: int, offset: int) -> tuple[list[contracts.WarehouseMigration], int]:
    """One page of the team's migrations, newest first, and the total count."""
    page, count = service.list_migrations(team_id=team_id, limit=limit, offset=offset)
    return _to_migrations(team_id, page), count


def get_migration(team_id: int, migration_id: UUID) -> contracts.WarehouseMigration | None:
    migration = service.get_migration(team_id=team_id, migration_id=migration_id)
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


def start_migration_upload(*, team_id: int, user_id: int, provider: str) -> contracts.WarehouseMigration:
    return _to_migration(service.start_upload(team_id=team_id, user_id=user_id, provider=provider))


def upload_migration_connections(
    team_id: int,
    migration_id: UUID,
    *,
    account: Mapping[str, Any] | None,
    destinations: Sequence[Mapping[str, Any]],
    connections: Sequence[contracts.MigrationConnectionUpload],
) -> contracts.WarehouseMigrationUpload | None:
    """Raises `WarehouseMigrationHasVendorKeyError` when PostHog reads the account with a key instead, and
    `WarehouseMigrationUploadTooLargeError` when the migration would grow too large."""
    result = service.upload_connections(
        team_id=team_id, migration_id=migration_id, account=account, destinations=destinations, connections=connections
    )
    if result is None:
        return None
    return contracts.WarehouseMigrationUpload(
        items=[_to_item(item) for item in result.items], errors=list(result.errors)
    )


def delete_migration(team_id: int, migration_id: UUID) -> bool:
    return service.delete_migration(team_id=team_id, migration_id=migration_id)


def refresh_migration(team_id: int, migration_id: UUID) -> contracts.WarehouseMigration | None:
    """Raises `WarehouseMigrationBusyError` while a crawl runs, and `WarehouseMigrationUploadedError` without a key."""
    migration = service.refresh_migration(team_id=team_id, migration_id=migration_id)
    return _to_migration(migration) if migration else None


def list_migration_items(
    team_id: int, migration_id: UUID, *, limit: int, offset: int
) -> tuple[list[contracts.WarehouseMigrationItem], int] | None:
    """One page of the migration's items and the total count. Returns None when the migration is not found."""
    result = service.list_items(team_id=team_id, migration_id=migration_id, limit=limit, offset=offset)
    if result is None:
        return None
    page, count = result
    return [_to_item(item) for item in page], count


def estimate_migration_cost(
    team_id: int, migration_id: UUID, usage: Sequence[contracts.MigrationUsageReport]
) -> contracts.WarehouseMigrationCostEstimate | None:
    """Monthly rows and list price per connection, from the usage the user reported. None when not found."""
    estimate = service.estimate_migration_cost(
        team_id=team_id,
        migration_id=migration_id,
        usage=[_to_reported_usage(report) for report in usage],
    )
    if estimate is None:
        return None
    confidences = Counter(connection.confidence for connection in estimate.connections)
    return contracts.WarehouseMigrationCostEstimate(
        items=[
            contracts.WarehouseMigrationCostItem(
                item_id=UUID(connection.item_id),
                name=connection.name,
                source_type=connection.source_type,
                confidence=contracts.WarehouseMigrationCostConfidence(connection.confidence),
                monthly_rows=connection.monthly_rows,
                monthly_cost_usd=connection.monthly_cost_usd,
                notes=list(connection.notes),
            )
            for connection in estimate.connections
        ],
        monthly_rows=estimate.monthly_rows,
        monthly_cost_usd=estimate.monthly_cost_usd,
        reported_count=confidences[Confidence.REPORTED],
        estimated_count=confidences[Confidence.ESTIMATED],
        unknown_count=confidences[Confidence.UNKNOWN],
        free_first_sync_days=FREE_HISTORICAL_WINDOW.days,
        unmatched_usage=[
            contracts.MigrationUsageReport(
                connection_name=report.connection_name,
                monthly_rows=report.monthly_rows,
                destination_id=report.destination_id,
                schema_name=report.schema_name,
                table_name=report.table_name,
            )
            for report in estimate.unmatched_usage
        ],
        price_tiers=[
            contracts.WarehouseMigrationPriceTier(
                up_to=tier.up_to, unit_amount_usd=tier.unit_amount_usd, flat_amount_usd=tier.flat_amount_usd
            )
            for tier in estimate.tiers
        ]
        if estimate.tiers is not None
        else None,
        usage_query=USAGE_QUERY,
    )


def _to_reported_usage(report: contracts.MigrationUsageReport) -> ReportedUsage:
    return ReportedUsage(
        connection_name=report.connection_name,
        monthly_rows=report.monthly_rows,
        destination_id=report.destination_id,
        schema_name=report.schema_name,
        table_name=report.table_name,
    )


def skip_migration_items(
    team_id: int,
    migration_id: UUID,
    *,
    item_ids: Sequence[UUID] | None = None,
    keep_item_ids: Sequence[UUID] | None = None,
) -> contracts.WarehouseMigrationBulkSkip | None:
    """Skip `item_ids`, or every item except `keep_item_ids`. Returns None when the migration is not found.

    Raises `WarehouseMigrationUnknownItemsError` when an id is not an item of the migration.
    """
    if not service.migration_exists(team_id=team_id, migration_id=migration_id):
        return None
    return service.skip_items(
        team_id=team_id, migration_id=migration_id, item_ids=item_ids, keep_item_ids=keep_item_ids
    )


def skip_migration_item(team_id: int, migration_id: UUID, item_id: UUID) -> contracts.WarehouseMigrationItem | None:
    """Raises `WarehouseMigrationItemClaimedError` once an apply claimed the item."""
    item = service.skip_item(team_id=team_id, migration_id=migration_id, item_id=item_id)
    return _to_item(item) if item else None


def find_migration_item(team_id: int, item_id: UUID) -> contracts.WarehouseMigrationItem | None:
    item = _WarehouseMigrationItem.objects.for_team(team_id).select_related("created_by").filter(id=item_id).first()
    return _to_item(item) if item else None


def prefill_mismatches(team_id: int, item_id: UUID, payload: Mapping[str, Any]) -> list[str] | None:
    """The prefilled settings of the item that `payload` changes, as dotted paths. None when the item is not found.

    The connect page shows these settings read-only, so a payload that changes one did not come from that page.
    """
    item = _WarehouseMigrationItem.objects.for_team(team_id).filter(id=item_id).first()
    if item is None:
        return None
    prefill = (item.proposal or {}).get("prefill") or {}
    return sorted(_changed_paths(prefill, payload, ()))


def _changed_paths(prefill: Mapping[str, Any], payload: Any, parents: tuple[str, ...]) -> list[str]:
    changed: list[str] = []
    for key, expected in prefill.items():
        path = (*parents, key)
        actual = payload.get(key) if isinstance(payload, Mapping) else None
        if isinstance(expected, Mapping):
            changed.extend(_changed_paths(expected, actual, path))
        # Forms send numbers and switches as strings or booleans, so compare the text.
        elif actual is None or str(actual).strip() != str(expected).strip():
            changed.append(".".join(path))
    return changed


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
    Raises `WarehouseMigrationTableOverrideError` when the table overrides do not fit the plan, and
    `WarehouseMigrationEmptySourceError` when the earlier attempt left a source with no tables.
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
    caveats = list(item.caveats)
    try:
        proposal = with_table_overrides(
            proposal,
            [TableOverride(vendor_table=o.vendor_table, posthog_table=o.posthog_table) for o in table_overrides],
            vendor_tables=_vendor_tables(item) if table_overrides else None,
            caps=source_capabilities(proposal.source_type),
            caveats=caveats,
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
        caveats=caveats,
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
    if not leftover.has_tables:
        message = _empty_leftover_error(leftover)
        # Back to the earlier claim, so the next attempt finds this source again until the user deletes it.
        items.update(
            status=_WarehouseMigrationItem.Status.FAILED,
            error=message,
            claimed_at=item.claimed_at,
            claimed_prefix=item.claimed_prefix,
            updated_at=timezone.now(),
        )
        raise contracts.WarehouseMigrationEmptySourceError(message)
    caveats = [*item.caveats, _LEFTOVER_CAVEAT]
    finish_migration_item(team_id, item.id, source_id=leftover.id, caveats=caveats)
    return dataclasses.replace(claimed, caveats=caveats, recovered_source_id=leftover.id)


def _vendor_tables(item: _WarehouseMigrationItem) -> dict[str, VendorTable]:
    """The item's enabled Fivetran tables by name, from the snapshot of the latest crawl."""
    snapshot = (
        _WarehouseMigration.objects.for_team(item.team_id)
        .filter(id=item.migration_id)
        .values_list("snapshot", flat=True)
        .first()
    )
    if not snapshot:
        return {}
    try:
        connections = VendorSnapshot.from_json(snapshot).connections
    except ValidationError:
        return {}
    tables: dict[str, VendorTable] = {}
    for connection in connections:
        if connection.id == item.vendor_connection_id:
            for table in connection.tables:
                if table.enabled:
                    tables.setdefault(table.name, table)
    return tables


_LEFTOVER_CAVEAT = "An earlier attempt created this source but did not finish. Check its tables and sync schedule."


def _source_description(item: _WarehouseMigrationItem) -> str:
    # The description holds 400 characters, and a vendor connection name can too.
    return f"Imported from the migrated connection {item.name[:350]}."


@frozen
class _LeftoverSource:
    id: UUID
    prefix: str | None
    # False when the attempt stopped before it created any table, so the source can never sync.
    has_tables: bool


def _empty_leftover_error(leftover: _LeftoverSource) -> str:
    name = f"`{leftover.prefix}`" if leftover.prefix else "without a prefix"
    return f"An earlier attempt created the source {name} but none of its tables. Delete that source, then apply again."


def _source_created_since_claim(item: _WarehouseMigrationItem, source_type: str) -> _LeftoverSource | None:
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
    source = sources.order_by("created_at").first()
    if source is None:
        return None
    return _LeftoverSource(id=source.id, prefix=source.prefix, has_tables=source.schemas.exists())


def plan_migration_schemas(
    proposal: Mapping, source_schemas: list[SourceSchema], permission_errors: Mapping[str, str | None]
) -> contracts.PlannedMigrationSchemas:
    planned = build_planned_schemas(ItemProposal.from_json(proposal), source_schemas, permission_errors)
    return contracts.PlannedMigrationSchemas(
        schemas=planned.schemas,
        unavailable=list(planned.unavailable),
        webhook_only=list(planned.webhook_only),
        planned=list(planned.planned),
        kept_off=list(planned.kept_off),
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
    if leftover is not None and leftover.has_tables:
        caveat = "Creating the source failed partway. The source exists, so check its tables and sync schedule."
        finish_migration_item(team_id, item_id, source_id=leftover.id, caveats=[*item.caveats, caveat])
        return
    _set_failed(team_id, item_id, _empty_leftover_error(leftover) if leftover is not None else error)


def _set_failed(team_id: int, item_id: UUID, error: str) -> None:
    _WarehouseMigrationItem.objects.for_team(team_id).filter(id=item_id).update(
        status=_WarehouseMigrationItem.Status.FAILED, error=error, updated_at=timezone.now()
    )


__all__ = [
    "ITEM_STATUS_CHOICES",
    "ITEM_VERDICT_CHOICES",
    "claim_migration_item",
    "fail_migration_item",
    "find_migration_item",
    "prefill_mismatches",
    "finish_migration_item",
    "plan_migration_schemas",
    "PROVIDER_CHOICES",
    "STATUS_CHOICES",
    "create_migration",
    "delete_migration",
    "estimate_migration_cost",
    "get_migration",
    "is_migration_import_enabled",
    "list_migration_items",
    "list_migrations",
    "refresh_migration",
    "skip_migration_item",
    "skip_migration_items",
    "start_migration_upload",
    "upload_migration_connections",
]
