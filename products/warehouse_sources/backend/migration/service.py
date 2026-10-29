from collections import Counter
from collections.abc import Sequence
from uuid import UUID

from django.db.models import Count
from django.utils import timezone

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.facade.contracts import (
    WarehouseMigrationBusyError,
    WarehouseMigrationItemClaimedError,
    WarehouseMigrationKeyRejectedError,
    WarehouseMigrationVendorUnreachableError,
)
from products.warehouse_sources.backend.migration.fivetran.client import (
    FivetranAPIError,
    FivetranAuthError,
    FivetranClient,
    FivetranCredentials,
)
from products.warehouse_sources.backend.models.warehouse_migration import WarehouseMigration, WarehouseMigrationItem
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.crawl_warehouse_migration import (
    start_crawl,
)

ITEM_COUNT_KEYS = ("as_is", "caveats", "unsupported", "applied", "skipped")


def create_migration(*, team_id: int, user_id: int, provider: str, api_key: str, api_secret: str) -> WarehouseMigration:
    """Check the key against the vendor, store it, and start reading the account."""
    credentials = FivetranCredentials(api_key=api_key, api_secret=api_secret)
    try:
        FivetranClient(credentials).get_account_info()
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


def refresh_migration(*, team_id: int, migration_id: UUID) -> WarehouseMigration | None:
    migration = WarehouseMigration.objects.for_team(team_id).filter(id=migration_id).first()
    if migration is None:
        return None
    if migration.status in (WarehouseMigration.Status.PENDING, WarehouseMigration.Status.CRAWLING):
        raise WarehouseMigrationBusyError()
    migration.status = WarehouseMigration.Status.PENDING
    migration.latest_error = ""
    migration.save(update_fields=["status", "latest_error", "updated_at"])
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
) -> tuple[list[UUID], list[UUID]]:
    """Skip the chosen items, or all but the kept ones. Returns the skipped ids and the ids an apply holds."""
    items = WarehouseMigrationItem.objects.for_team(team_id).filter(migration_id=migration_id)
    chosen = items.filter(id__in=item_ids) if item_ids is not None else items.exclude(id__in=keep_item_ids or [])
    # The same conditional update as a single skip, so an apply that claimed an item keeps it.
    chosen.filter(status__in=(WarehouseMigrationItem.Status.PENDING, WarehouseMigrationItem.Status.FAILED)).update(
        status=WarehouseMigrationItem.Status.SKIPPED, updated_at=timezone.now()
    )
    skipped: list[UUID] = []
    not_skipped: list[UUID] = []
    for item_id, status in chosen.order_by("name").values_list("id", "status"):
        (skipped if status == WarehouseMigrationItem.Status.SKIPPED else not_skipped).append(item_id)
    return skipped, not_skipped


def item_counts(migration: WarehouseMigration) -> dict[str, int]:
    counts: Counter[str] = Counter()
    rows = (
        WarehouseMigrationItem.objects.for_team(migration.team_id)
        .filter(migration=migration)
        .values("status", "verdict")
        .annotate(count=Count("id"))
    )
    for row in rows:
        counts[row["status"]] += row["count"]
        # Verdict counts cover only the connections still left to move.
        if row["status"] not in (WarehouseMigrationItem.Status.APPLIED, WarehouseMigrationItem.Status.SKIPPED):
            counts[row["verdict"]] += row["count"]
    return {key: counts[key] for key in ITEM_COUNT_KEYS}


def _start_crawl(migration: WarehouseMigration) -> None:
    rows = WarehouseMigration.objects.for_team(migration.team_id).filter(id=migration.id)
    try:
        migration.workflow_id = start_crawl(team_id=migration.team_id, migration_id=migration.id)
    except Exception as error:
        # Otherwise the migration stays `pending` and a refresh refuses to start it again.
        capture_exception(error)
        migration.status = WarehouseMigration.Status.FAILED
        migration.latest_error = "PostHog could not start reading the Fivetran account. Try again."
        # Conditional, so a crawl that did start and already set `crawling` keeps its status.
        rows.filter(status=WarehouseMigration.Status.PENDING).update(
            status=migration.status, latest_error=migration.latest_error, updated_at=timezone.now()
        )
        return
    # Only the workflow id: the crawl can set `crawling` before this line runs.
    rows.update(workflow_id=migration.workflow_id, updated_at=timezone.now())
