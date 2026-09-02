"""Snapshot persistence into the local duckgres usage mirror.

Because acks only ever happen at UTC day boundaries, every pull's response
carries complete day-so-far totals for the whole un-acked window. Applying a
healthy organization is therefore a replace, not an increment. Production
promotion compares canonical org/product/day totals first: a decrease or
omission retains that org's last-good rows while independent orgs advance.
`replace_window` remains the lower-level all-or-nothing primitive used by its
focused tests.

Watermark subtlety: duckgres watermarks are bucket-START labels and ack
deletes `bucket_start <= watermark`, so our day-boundary acks are
`start_of_open_day - 1s` (23:59:59 of the last complete day). The window's
first date is derived as `(watermark_low + 1s).date()` — deriving from
`watermark_low.date()` would delete the already-acked previous day, which
duckgres will never re-serve.
"""

import datetime as dt
import dataclasses
from collections import defaultdict
from decimal import Decimal

from django.db import transaction

import structlog

from products.managed_warehouse.backend.models import DuckgresDailyStorageUsage, DuckgresDailyUsage
from products.managed_warehouse.backend.temporal.duckgres_usage.client import StorageRow, UsageResponse, UsageRow

logger = structlog.get_logger(__name__)

ENDPOINTS_QUERY_SOURCE = "endpoints"


@dataclasses.dataclass(frozen=True)
class PromotionResult:
    rows_written: int
    regressed_org_ids: set[str] = dataclasses.field(default_factory=set)


def derive_window(watermark_low: dt.datetime, watermark_high: dt.datetime) -> tuple[dt.date, dt.date]:
    """The [first, last] UTC-date window whose rows a response may replace.

    Rows dated outside it are already-acked (below `window_first`) or beyond the
    served ceiling, and are never persisted — acked days are immutable. Deriving
    `window_first` from `watermark_low + 1s` (not `watermark_low.date()`) is what
    keeps the last acked day out of the window.
    """
    window_first = (watermark_low + dt.timedelta(seconds=1)).astimezone(dt.UTC).date()
    window_last = watermark_high.astimezone(dt.UTC).date()
    return window_first, window_last


def count_out_of_window_rows(response: UsageResponse) -> int:
    """Rows (either family) dated outside the replace window.

    A row outside the window means duckgres served data at or below its own
    cursor — a contract violation. `replace_window` drops these rather than
    mutate already-billed history; the caller alerts and withholds the ack so
    the ack can't delete the dropped rows' source buckets.
    """
    if response.watermark_high <= response.watermark_low:
        return 0
    first, last = derive_window(response.watermark_low, response.watermark_high)
    return sum(1 for row in response.rows if not first <= row.date <= last) + sum(
        1 for row in response.storage_rows if not first <= row.date <= last
    )


def replace_window(response: UsageResponse) -> int:
    """Replace the open window's mirror rows with the response's rows.

    Returns the number of rows written. Rows dated outside the window are dropped
    (see `count_out_of_window_rows`); the caller is responsible for alerting on
    and withholding the ack for them.
    """
    if response.watermark_high <= response.watermark_low:
        # Empty window (fresh cursor, or a pull racing right behind an ack).
        if response.rows or response.storage_rows:
            logger.warning(
                "duckgres_usage_rows_in_empty_window_skipped",
                watermark_low=response.watermark_low.isoformat(),
                row_count=len(response.rows) + len(response.storage_rows),
            )
        return 0

    window_first, window_last = derive_window(response.watermark_low, response.watermark_high)

    # Acked days are immutable: replace strictly within the window. Out-of-window
    # rows are dropped (the activity captures + withholds the ack for them).
    compute_rows = [row for row in response.rows if window_first <= row.date <= window_last]
    storage_rows = [row for row in response.storage_rows if window_first <= row.date <= window_last]

    # BOTH families commit in this one transaction: duckgres's ack deletes
    # compute AND storage buckets atomically, so persisting one family and
    # acking would permanently destroy the other's un-persisted data.
    #
    # An empty family never deletes: a missing or empty usage array must not be
    # read as "this window dropped to zero" and wipe good mirror rows. duckgres
    # serves complete day-so-far totals and an acked day is immutable, so a day
    # that once had usage never legitimately comes back empty — an empty family
    # means "nothing to say about it this pull", so we leave what we already have.
    # A populated family still fully replaces its window, which is the whole point.
    with transaction.atomic():
        if compute_rows:
            DuckgresDailyUsage.objects.filter(date__gte=window_first, date__lte=window_last).delete()
        if storage_rows:
            DuckgresDailyStorageUsage.objects.filter(date__gte=window_first, date__lte=window_last).delete()
        created = DuckgresDailyUsage.objects.bulk_create(
            DuckgresDailyUsage(
                date=row.date,
                organization_id=row.org_id,
                team_id=row.team_id,
                query_source=row.query_source,
                cpu=row.cpu,
                mem_gib=row.mem_gib,
                cpu_seconds=row.cpu_seconds,
                memory_seconds=row.memory_seconds,
            )
            for row in compute_rows
        )
        created_storage = DuckgresDailyStorageUsage.objects.bulk_create(
            DuckgresDailyStorageUsage(
                date=row.date,
                organization_id=row.org_id,
                team_id=row.team_id,
                gib_seconds=row.gib_seconds,
            )
            for row in storage_rows
        )
    return len(created) + len(created_storage)


def promote_window(
    response: UsageResponse,
    *,
    blocked_org_ids: set[str] | None = None,
    block_all: bool = False,
) -> PromotionResult:
    """Promote a snapshot without letting one bad org regress another.

    Totals are compared at the billing boundary: organization, UTC day, and
    product (standard compute, endpoints compute, or storage). Worker-size and
    team-attribution changes may legitimately reshape rows while preserving the
    same billable total, so neither is part of the monotonicity key.
    """
    if block_all or response.watermark_high <= response.watermark_low:
        return PromotionResult(rows_written=0)

    window_first, window_last = derive_window(response.watermark_low, response.watermark_high)
    compute_rows = [row for row in response.rows if window_first <= row.date <= window_last]
    storage_rows = [row for row in response.storage_rows if window_first <= row.date <= window_last]

    existing_compute = list(
        DuckgresDailyUsage.objects.filter(date__gte=window_first, date__lte=window_last).values(
            "organization_id",
            "date",
            "team_id",
            "query_source",
            "cpu",
            "mem_gib",
            "cpu_seconds",
            "memory_seconds",
        )
    )
    existing_storage = list(
        DuckgresDailyStorageUsage.objects.filter(date__gte=window_first, date__lte=window_last).values(
            "organization_id", "date", "team_id", "gib_seconds"
        )
    )

    old_compute: defaultdict[tuple[str, dt.date, bool], int] = defaultdict(int)
    new_compute: defaultdict[tuple[str, dt.date, bool], int] = defaultdict(int)
    for row in existing_compute:
        key = (str(row["organization_id"]), row["date"], row["query_source"] == ENDPOINTS_QUERY_SOURCE)
        old_compute[key] += row["cpu_seconds"] * 8 + row["memory_seconds"]
    for row in compute_rows:
        key = (row.org_id, row.date, row.query_source == ENDPOINTS_QUERY_SOURCE)
        new_compute[key] += row.cpu_seconds * 8 + row.memory_seconds

    old_storage: defaultdict[tuple[str, dt.date], Decimal] = defaultdict(Decimal)
    new_storage: defaultdict[tuple[str, dt.date], Decimal] = defaultdict(Decimal)
    for row in existing_storage:
        old_storage[(str(row["organization_id"]), row["date"])] += row["gib_seconds"]
    for row in storage_rows:
        new_storage[(row.org_id, row.date)] += row.gib_seconds

    regressed_org_ids = {
        scope[0]
        for scope, total in old_compute.items()
        if scope not in response.invalid_compute_scopes and new_compute[scope] < total
    }
    regressed_org_ids.update(
        scope[0]
        for scope, total in old_storage.items()
        if scope not in response.invalid_storage_scopes and new_storage[scope] < total
    )

    blocked = set(blocked_org_ids or ()) | regressed_org_ids
    incoming_org_ids = {row.org_id for row in compute_rows} | {row.org_id for row in storage_rows}
    promotable_org_ids = incoming_org_ids - blocked
    # An invalid row is nonrecoverable, so it must not wedge the shared ack, but
    # neither may an unrelated valid product cause us to delete that product's
    # last-good value. Freeze only the invalid org/day/product scope and promote
    # every other valid scope for the organization.
    promotable_compute = [
        row
        for row in compute_rows
        if row.org_id in promotable_org_ids
        and (row.org_id, row.date, row.query_source == ENDPOINTS_QUERY_SOURCE) not in response.invalid_compute_scopes
    ]
    for row in existing_compute:
        org_id = str(row["organization_id"])
        scope = (org_id, row["date"], row["query_source"] == ENDPOINTS_QUERY_SOURCE)
        if org_id in promotable_org_ids and scope in response.invalid_compute_scopes:
            promotable_compute.append(
                UsageRow(
                    date=row["date"],
                    org_id=org_id,
                    team_id=row["team_id"],
                    query_source=row["query_source"],
                    cpu=row["cpu"],
                    mem_gib=row["mem_gib"],
                    cpu_seconds=row["cpu_seconds"],
                    memory_seconds=row["memory_seconds"],
                )
            )

    promotable_storage = [
        row
        for row in storage_rows
        if row.org_id in promotable_org_ids and (row.org_id, row.date) not in response.invalid_storage_scopes
    ]
    for row in existing_storage:
        org_id = str(row["organization_id"])
        scope = (org_id, row["date"])
        if org_id in promotable_org_ids and scope in response.invalid_storage_scopes:
            promotable_storage.append(
                StorageRow(
                    date=row["date"],
                    org_id=org_id,
                    team_id=row["team_id"],
                    gib_seconds=row["gib_seconds"],
                )
            )

    with transaction.atomic():
        if promotable_org_ids:
            DuckgresDailyUsage.objects.filter(
                date__gte=window_first,
                date__lte=window_last,
                organization_id__in=promotable_org_ids,
            ).delete()
            DuckgresDailyStorageUsage.objects.filter(
                date__gte=window_first,
                date__lte=window_last,
                organization_id__in=promotable_org_ids,
            ).delete()
        created = DuckgresDailyUsage.objects.bulk_create(
            DuckgresDailyUsage(
                date=row.date,
                organization_id=row.org_id,
                team_id=row.team_id,
                query_source=row.query_source,
                cpu=row.cpu,
                mem_gib=row.mem_gib,
                cpu_seconds=row.cpu_seconds,
                memory_seconds=row.memory_seconds,
            )
            for row in promotable_compute
        )
        created_storage = DuckgresDailyStorageUsage.objects.bulk_create(
            DuckgresDailyStorageUsage(
                date=row.date,
                organization_id=row.org_id,
                team_id=row.team_id,
                gib_seconds=row.gib_seconds,
            )
            for row in promotable_storage
        )

    return PromotionResult(
        rows_written=len(created) + len(created_storage),
        regressed_org_ids=regressed_org_ids,
    )
