"""Activities for the duckgres usage poll.

Two activities, split on purpose:

- **poll_duckgres_usage** — fetch the un-acked window, persist it to the mirror,
  and *decide* the ack, but don't perform it. The fetched rows can be tens of MB
  at scale, so they can't cross the workflow boundary as an activity return
  value — fetch and persist must live together here.
- **ack_duckgres_usage** — perform the ack POST. Separate so a transient ack
  failure retries just the POST, not the whole (large) fetch+persist.

Two custody rules hold across the split:

- **commit before ack** — the poll commits the rows before it returns, and the
  workflow only acks after that, so duckgres is never told to delete unpersisted data.
- **record before ack** — the poll writes the watermark it will ack in the same
  transaction as the rows, so an ack that never lands (crash, exhausted retries)
  leaves our record *ahead* of duckgres — the benign "duckgres behind" direction
  that self-heals (re-acks) on the next pull.

Everything that can be wrong with a pull is an *anomaly* (`anomalies.py`): one
table where each kind carries its detection, its alert, and one policy bit —
`recoverable` (a re-pull can still capture the data → withhold the ack) or not
(permanently bad → drop, alert, ack proceeds). The ack decision is derived from
that table, never hand-assembled here.
"""

import datetime as dt
import dataclasses

from django.db import transaction

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.managed_warehouse.backend.models import DuckgresUsageCursor
from products.managed_warehouse.backend.temporal.duckgres_usage.acking import day_boundary_ack
from products.managed_warehouse.backend.temporal.duckgres_usage.anomalies import (
    Anomaly,
    detect_anomalies,
    regression_anomaly,
)
from products.managed_warehouse.backend.temporal.duckgres_usage.client import (
    UsageResponse,
    ack_usage,
    fetch_usage,
    is_configured,
)
from products.managed_warehouse.backend.temporal.duckgres_usage.mirror import count_out_of_window_rows, promote_window
from products.managed_warehouse.backend.temporal.duckgres_usage.team_resolution import (
    ResolvedTeams,
    resolve_billing_teams,
)
from products.managed_warehouse.backend.temporal.duckgres_usage.types import (
    PollDuckgresUsageInputs,
    PollDuckgresUsageResult,
)

logger = structlog.get_logger(__name__)


@activity.defn(name="poll-duckgres-usage")
async def poll_duckgres_usage(inputs: PollDuckgresUsageInputs) -> PollDuckgresUsageResult:
    async with Heartbeater():
        if not is_configured():
            await logger.ainfo("duckgres_usage_poll_skipped_not_configured")
            return PollDuckgresUsageResult(skipped=True)

        response = await sync_to_async(fetch_usage)()

        # Resolve billing teams up front (needs the Team table, so sync DB context):
        # re-attribute deleted/unknown-team rows to a billable surrogate and surface
        # any duplicates, value-conflicts, and orphan orgs. The conflict
        # count feeds the ack decision below, so it must be known before should_ack.
        resolution = await database_sync_to_async(resolve_billing_teams)(response.rows, response.storage_rows)

        recorded = await database_sync_to_async(_read_recorded_watermark)()
        out_of_window = count_out_of_window_rows(response)
        anomalies = detect_anomalies(response, resolution, recorded, out_of_window)
        if recorded is not None and response.watermark_low < recorded:
            # Duckgres re-serves data we already acked past; snapshot promotion
            # absorbs it idempotently. Worth noting, not halting.
            logger.warning(
                "duckgres_usage_watermark_behind",
                recorded=recorded.isoformat(),
                server_watermark_low=response.watermark_low.isoformat(),
            )

        ack_at = day_boundary_ack(watermark_low=response.watermark_low, watermark_high=response.watermark_high)
        watermark_hole = any(a.kind == "watermark_hole" for a in anomalies)

        persisted = await database_sync_to_async(_persist)(response, resolution, ack_at, anomalies)
        if persisted.regressed_org_ids:
            anomalies.append(regression_anomaly(persisted.regressed_org_ids))
        ack_watermark = ack_at.isoformat() if (persisted.should_ack and ack_at is not None) else None

        # Every anomaly is loud — one capture per kind, with its policy already
        # applied to the ack decision above. See anomalies.py for the whole table.
        for anomaly in anomalies:
            capture_exception(anomaly.to_exception())

        await logger.ainfo(
            "duckgres_usage_polled",
            rows_written=persisted.rows_written,
            row_count=len(response.rows),
            storage_row_count=len(response.storage_rows),
            watermark_low=response.watermark_low.isoformat(),
            watermark_high=response.watermark_high.isoformat(),
            ack_watermark=ack_watermark,
            anomalies=[a.kind for a in anomalies],
            unparsed_row_count=response.unparsed_row_count,
            out_of_window_dropped=out_of_window,
            orphaned_org_ids=sorted(resolution.orphaned_org_ids),
            regressed_org_ids=sorted(persisted.regressed_org_ids),
        )
        return PollDuckgresUsageResult(
            rows_written=persisted.rows_written,
            watermark_low=response.watermark_low.isoformat(),
            watermark_high=response.watermark_high.isoformat(),
            ack_watermark=ack_watermark,
            watermark_hole=watermark_hole,
            unparsed_row_count=response.unparsed_row_count,
            out_of_window_dropped=out_of_window,
            orphaned_org_ids=sorted(resolution.orphaned_org_ids),
            malformed_org_row_count=resolution.malformed_org_row_count,
        )


@activity.defn(name="ack-duckgres-usage")
async def ack_duckgres_usage(ack_watermark: str) -> None:
    """Ack the watermark the poll activity committed. Its own activity so a
    transient failure retries just this POST. Idempotent on duckgres (re-acking
    the same watermark is a no-op)."""
    await sync_to_async(ack_usage)(dt.datetime.fromisoformat(ack_watermark))


def _read_recorded_watermark() -> dt.datetime | None:
    cursor = DuckgresUsageCursor.objects.first()
    return cursor.last_acked_watermark if cursor is not None else None


@dataclasses.dataclass(frozen=True)
class _PersistenceResult:
    rows_written: int
    should_ack: bool
    regressed_org_ids: set[str] = dataclasses.field(default_factory=set)


def _persist(
    response: UsageResponse,
    resolution: ResolvedTeams,
    ack_at: dt.datetime | None,
    anomalies: list[Anomaly],
) -> _PersistenceResult:
    # Persist the already-resolved rows (team re-attribution + dedup happened in
    # resolve_billing_teams, up in the activity where the ack decision needs its
    # counts). Swap the resolved rows onto the response, promote the open window, and
    # — record-before-ack — write the watermark in the same transaction.
    #
    # The replace is MONOTONE in the served watermark_high: a response at or below
    # the last applied one never replaces rows. This is what stops a zombie poll
    # attempt (timed out on heartbeat, but its process and DB connection survived)
    # from landing a stale pre-midnight snapshot AFTER a newer attempt already
    # applied the day's final totals and acked — an acked day is deleted upstream,
    # so a stale overwrite would be permanent and silent. The row lock makes the
    # compare-and-replace atomic: a concurrent writer blocks here, then re-reads the
    # committed watermark and refuses.
    #
    # The ack path is deliberately NOT gated on staleness: a skipped response's
    # ack boundary is at or below what the mirror already reflects, so acking it is
    # a safe idempotent re-ack — refusing it could strand duckgres behind forever
    # when it re-serves an identical window after a lost ack. The cursor write only
    # ever advances, which closes the long-stall variant (a zombie recording an
    # older watermark computed before its stall).
    resolved = dataclasses.replace(response, rows=resolution.compute_rows, storage_rows=resolution.storage_rows)
    recoverable = [anomaly for anomaly in anomalies if anomaly.recoverable]
    block_all = any(anomaly.organization_ids is None for anomaly in recoverable)
    blocked_org_ids = {
        org_id for anomaly in recoverable if anomaly.organization_ids is not None for org_id in anomaly.organization_ids
    }
    with transaction.atomic():
        cursor, _ = DuckgresUsageCursor.objects.select_for_update().get_or_create(singleton=1)
        stale = cursor.last_applied_watermark is not None and (
            response.watermark_high < cursor.last_applied_watermark
            or (
                response.watermark_high == cursor.last_applied_watermark
                and cursor.last_complete_watermark is not None
                and cursor.last_complete_watermark >= response.watermark_high
            )
        )
        if stale:
            rows_written = 0
            regressed_org_ids: set[str] = set()
            logger.warning(
                "duckgres_usage_stale_response_skipped",
                response_watermark_high=response.watermark_high.isoformat(),
                last_applied_watermark=cursor.last_applied_watermark.isoformat()
                if cursor.last_applied_watermark
                else None,
            )
        else:
            promotion = promote_window(resolved, blocked_org_ids=blocked_org_ids, block_all=block_all)
            rows_written = promotion.rows_written
            regressed_org_ids = promotion.regressed_org_ids
            cursor.last_applied_watermark = response.watermark_high
            if (
                not recoverable
                and not regressed_org_ids
                and (cursor.last_complete_watermark is None or response.watermark_high > cursor.last_complete_watermark)
            ):
                cursor.last_complete_watermark = response.watermark_high

        should_ack = ack_at is not None and not recoverable and not regressed_org_ids
        if (
            should_ack
            and ack_at is not None
            and (cursor.last_acked_watermark is None or ack_at > cursor.last_acked_watermark)
        ):
            cursor.last_acked_watermark = ack_at
        cursor.save(
            update_fields=[
                "last_applied_watermark",
                "last_complete_watermark",
                "last_acked_watermark",
                "updated_at",
            ]
        )
    return _PersistenceResult(
        rows_written=rows_written,
        should_ack=should_ack,
        regressed_org_ids=regressed_org_ids,
    )
