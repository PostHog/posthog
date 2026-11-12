from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Count, QuerySet
from django.utils import timezone

from pydantic import ValidationError
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.facade.contracts import (
    MigrationConnectionUpload,
    WarehouseMigrationBulkSkip,
    WarehouseMigrationBusyError,
    WarehouseMigrationHasVendorKeyError,
    WarehouseMigrationItemClaimedError,
    WarehouseMigrationKeyRejectedError,
    WarehouseMigrationUnknownItemsError,
    WarehouseMigrationUploadedError,
    WarehouseMigrationVendorUnreachableError,
)
from products.warehouse_sources.backend.migration import catalog
from products.warehouse_sources.backend.migration.cost import (
    CostedConnection,
    CostEstimate,
    ReportedUsage,
    estimate_cost,
)
from products.warehouse_sources.backend.migration.crawl import plan_snapshot, save_plan
from products.warehouse_sources.backend.migration.fivetran.client import (
    FivetranAPIError,
    FivetranAuthError,
    FivetranClient,
    FivetranCredentials,
)
from products.warehouse_sources.backend.migration.fivetran.snapshot import merge_upload
from products.warehouse_sources.backend.migration.pricing import row_price_tiers
from products.warehouse_sources.backend.migration.types import ItemProposal, VendorSnapshot
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.crawl_warehouse_migration import (
    new_crawl_workflow_id,
    start_crawl,
)

ITEM_COUNT_KEYS = ("as_is", "caveats", "unsupported", "applied", "skipped")
_KEY_CHECK_TIMEOUT_SECONDS = (5.0, 15.0)


def _migrations(team_id: int) -> QuerySet[WarehouseMigration]:
    # The snapshot can be large and no endpoint returns it.
    return WarehouseMigration.objects.for_team(team_id).defer("snapshot")


def list_migrations(*, team_id: int, limit: int, offset: int) -> tuple[list[WarehouseMigration], int]:
    """One page of the team's migrations, newest first, and the total count."""
    migrations = _migrations(team_id)
    return list(migrations.order_by("-created_at", "-id")[offset : offset + limit]), migrations.count()


def get_migration(*, team_id: int, migration_id: UUID) -> WarehouseMigration | None:
    return _migrations(team_id).filter(id=migration_id).first()


def migration_exists(*, team_id: int, migration_id: UUID) -> bool:
    return _migrations(team_id).filter(id=migration_id).exists()


def delete_migration(*, team_id: int, migration_id: UUID) -> bool:
    deleted, _ = WarehouseMigration.objects.for_team(team_id).filter(id=migration_id).delete()
    return bool(deleted)


def list_items(
    *, team_id: int, migration_id: UUID, limit: int, offset: int
) -> tuple[list[WarehouseMigrationItem], int] | None:
    """One page of the migration's items and the total count. Returns None when the migration is not found."""
    if not migration_exists(team_id=team_id, migration_id=migration_id):
        return None
    items = WarehouseMigrationItem.objects.for_team(team_id).filter(migration_id=migration_id)
    page = items.select_related("created_by").order_by("verdict", "name", "id")[offset : offset + limit]
    return list(page), items.count()


def create_migration(*, team_id: int, user_id: int, provider: str, api_key: str, api_secret: str) -> WarehouseMigration:
    """Check the key against the vendor, store it, and start reading the account."""
    credentials = FivetranCredentials(api_key=api_key, api_secret=api_secret)
    try:
        # One quick try: this runs inside the web request, and a client that times out sends the request again.
        FivetranClient(credentials, retry=Retry(total=0), timeout=_KEY_CHECK_TIMEOUT_SECONDS).get_account_info()
    except FivetranAuthError as error:
        raise WarehouseMigrationKeyRejectedError() from error
    except FivetranAPIError as error:
        raise WarehouseMigrationVendorUnreachableError() from error

    migration = WarehouseMigration.objects.for_team(team_id).create(
        team_id=team_id,
        created_by_id=user_id,
        provider=provider,
        credentials={"api_key": api_key, "api_secret": api_secret},
    )
    _start_crawl(migration)
    return migration


def start_upload(*, team_id: int, user_id: int, provider: str) -> WarehouseMigration:
    """A migration that an agent fills by uploading what it read from the vendor. PostHog gets no vendor key."""
    return WarehouseMigration.objects.for_team(team_id).create(
        team_id=team_id, created_by_id=user_id, provider=provider, status=WarehouseMigration.Status.READY
    )


@frozen
class UploadResult:
    items: list[WarehouseMigrationItem]
    errors: tuple[str, ...]


def upload_connections(
    *,
    team_id: int,
    migration_id: UUID,
    account: Mapping[str, Any] | None,
    destinations: Sequence[Mapping[str, Any]],
    connections: Sequence[MigrationConnectionUpload],
) -> UploadResult | None:
    """Plan the uploaded connections and merge them into the migration. Other items stay as they are."""
    with transaction.atomic():
        # Locked so two uploads cannot overwrite each other's snapshot.
        migration = (
            WarehouseMigration.objects.for_team(team_id)
            .select_for_update(of=("self",))
            .select_related("created_by")
            .filter(id=migration_id)
            .first()
        )
        if migration is None:
            return None
        if migration.credentials:
            raise WarehouseMigrationHasVendorKeyError()
        previous = VendorSnapshot.from_json(migration.snapshot) if migration.snapshot else None
        upload = merge_upload(previous, account=account, destinations=destinations, connections=connections)
        planned = plan_snapshot(migration, upload.snapshot, connection_ids=upload.connection_ids)
        save_plan(migration, upload.snapshot, planned, replace_all=False)
    items = WarehouseMigrationItem.objects.for_team(team_id).filter(
        migration_id=migration_id, vendor_connection_id__in=upload.connection_ids
    )
    return UploadResult(items=list(items.order_by("verdict", "name")), errors=upload.errors)


def refresh_migration(*, team_id: int, migration_id: UUID) -> WarehouseMigration | None:
    migrations = WarehouseMigration.objects.for_team(team_id).filter(id=migration_id)
    migration = migrations.first()
    if migration is None:
        return None
    # Checked before the claim below, which would otherwise leave an uploaded migration `pending` for good.
    if not migration.credentials:
        raise WarehouseMigrationUploadedError()
    # Conditional, so two refreshes cannot both start a crawl and the second terminate the first.
    claimed = migrations.exclude(
        status__in=(WarehouseMigration.Status.PENDING, WarehouseMigration.Status.CRAWLING)
    ).update(status=WarehouseMigration.Status.PENDING, latest_error="", updated_at=timezone.now())
    migration = migrations.first()
    if migration is None:
        return None
    if not claimed:
        raise WarehouseMigrationBusyError()
    _start_crawl(migration)
    return migration


def skip_item(*, team_id: int, migration_id: UUID, item_id: UUID) -> WarehouseMigrationItem | None:
    items = WarehouseMigrationItem.objects.for_team(team_id).filter(migration_id=migration_id, id=item_id)
    # Conditional, so a skip cannot overwrite an apply that claimed the item first.
    skipped = items.filter(
        status__in=(WarehouseMigrationItem.Status.PENDING, WarehouseMigrationItem.Status.FAILED)
    ).update(status=WarehouseMigrationItem.Status.SKIPPED, updated_at=timezone.now())
    item = items.first()
    if item is not None and not skipped and item.status != WarehouseMigrationItem.Status.SKIPPED:
        raise WarehouseMigrationItemClaimedError()
    return item


def skip_items(
    *,
    team_id: int,
    migration_id: UUID,
    item_ids: Sequence[UUID] | None,
    keep_item_ids: Sequence[UUID] | None,
) -> WarehouseMigrationBulkSkip:
    """Skip the chosen items, or all but the kept ones.

    Raises `WarehouseMigrationUnknownItemsError` before skipping anything when an id is not an item of the
    migration, since a mistyped kept id would otherwise skip the connection it meant to keep.
    """
    items = WarehouseMigrationItem.objects.for_team(team_id).filter(migration_id=migration_id)
    named = set(item_ids if item_ids is not None else keep_item_ids or [])
    unknown = named - set(items.filter(id__in=named).values_list("id", flat=True))
    if unknown:
        raise WarehouseMigrationUnknownItemsError(sorted(unknown, key=str))
    chosen = items.filter(id__in=item_ids) if item_ids is not None else items.exclude(id__in=keep_item_ids or [])
    # The same conditional update as a single skip, so an apply that claimed an item keeps it.
    chosen.filter(status__in=(WarehouseMigrationItem.Status.PENDING, WarehouseMigrationItem.Status.FAILED)).update(
        status=WarehouseMigrationItem.Status.SKIPPED, updated_at=timezone.now()
    )
    skipped: list[UUID] = []
    not_skipped: list[UUID] = []
    for item_id, status in chosen.order_by("name").values_list("id", "status"):
        (skipped if status == WarehouseMigrationItem.Status.SKIPPED else not_skipped).append(item_id)
    return WarehouseMigrationBulkSkip(skipped_item_ids=skipped, not_skipped_item_ids=not_skipped)


def item_counts(*, team_id: int, migration_ids: Sequence[UUID]) -> dict[UUID, dict[str, int]]:
    """The item counts of each migration, from one query for the whole page."""
    counts: dict[UUID, Counter[str]] = {migration_id: Counter() for migration_id in migration_ids}
    rows = (
        WarehouseMigrationItem.objects.for_team(team_id)
        .filter(migration_id__in=migration_ids)
        .values("migration_id", "status", "verdict")
        .annotate(count=Count("id"))
    )
    for row in rows:
        counter = counts[row["migration_id"]]
        counter[row["status"]] += row["count"]
        # Verdict counts cover only the connections still left to move.
        if row["status"] not in (WarehouseMigrationItem.Status.APPLIED, WarehouseMigrationItem.Status.SKIPPED):
            counter[row["verdict"]] += row["count"]
    return {migration_id: {key: counter[key] for key in ITEM_COUNT_KEYS} for migration_id, counter in counts.items()}


def estimate_migration_cost(*, team_id: int, migration_id: UUID, usage: Sequence[ReportedUsage]) -> CostEstimate | None:
    """Price the migration's connections from the reported usage. None when the migration is not found.

    Skipped and unsupported connections are left out.
    """
    if not migration_exists(team_id=team_id, migration_id=migration_id):
        return None
    items = WarehouseMigrationItem.objects.for_team(team_id).filter(migration_id=migration_id).order_by("name", "id")
    kept: list[tuple[WarehouseMigrationItem, ItemProposal]] = []
    left_out_names: list[str] = []
    for item in items:
        proposal = _valid_proposal(item.proposal)
        if proposal is None or item.status == WarehouseMigrationItem.Status.SKIPPED:
            left_out_names.append(item.name)
        else:
            kept.append((item, proposal))
    names = Counter([*(item.name.lower() for item, _ in kept), *(name.lower() for name in left_out_names)])
    # Only read when two connections share a name, since the snapshot can be large. A skipped connection counts, so
    # its usage, named by destination, does not land on the kept one.
    destinations = _destination_ids(team_id, migration_id) if any(count > 1 for count in names.values()) else {}
    connections = [
        CostedConnection(
            item_id=str(item.id),
            name=item.name,
            destination_id=destinations.get(item.vendor_connection_id),
            proposal=proposal,
        )
        for item, proposal in kept
    ]
    return estimate_cost(
        connections,
        usage,
        default_sync_types=catalog.default_sync_types,
        tiers=row_price_tiers(),
        left_out_names=left_out_names,
    )


def _valid_proposal(proposal: Mapping[str, Any] | None) -> ItemProposal | None:
    if proposal is None:
        return None
    try:
        return ItemProposal.from_json(proposal)
    except ValidationError:
        return None


def _destination_ids(team_id: int, migration_id: UUID) -> dict[str, str]:
    snapshot = (
        WarehouseMigration.objects.for_team(team_id).filter(id=migration_id).values_list("snapshot", flat=True).first()
    )
    if not snapshot:
        return {}
    try:
        connections = VendorSnapshot.from_json(snapshot).connections
    except ValidationError:
        return {}
    return {connection.id: connection.destination_id for connection in connections if connection.destination_id}


def _start_crawl(migration: WarehouseMigration) -> None:
    rows = WarehouseMigration.objects.for_team(migration.team_id).filter(id=migration.id)
    # Stored before the start, so the crawl finds its own id however fast it runs, and an older crawl stops writing.
    migration.workflow_id = new_crawl_workflow_id(migration.id)
    rows.update(workflow_id=migration.workflow_id, updated_at=timezone.now())
    try:
        start_crawl(team_id=migration.team_id, migration_id=migration.id, workflow_id=migration.workflow_id)
    except Exception as error:
        # Otherwise the migration stays `pending` and a refresh refuses to start it again.
        capture_exception(error)
        # Conditional, so a crawl that did start and already set `crawling` keeps its status.
        rows.filter(status=WarehouseMigration.Status.PENDING).update(
            status=WarehouseMigration.Status.FAILED,
            latest_error="PostHog could not start reading the Fivetran account. Try again.",
            updated_at=timezone.now(),
        )
        migration.refresh_from_db(fields=["status", "latest_error", "updated_at"])
        return
