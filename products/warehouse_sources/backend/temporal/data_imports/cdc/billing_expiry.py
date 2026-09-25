"""Stop CDC on a source whose team stays over the billing limit for longer than the buffer keeps changes.

Capture has no billing check: it keeps reading the slot and writing the buffer while the limit blocks
every load. Once a blocked table's oldest unread change is older than the buffer retention, the
lifecycle rule starts deleting changes the table never loaded, so only a re-snapshot can make it
correct again. From then on the slot costs the customer WAL and the buffer costs storage for data
that will never load. The source moves to the broken state, and Repair CDC re-snapshots every table
once the team is back under the limit.
"""

from __future__ import annotations

import uuid
import typing
import datetime as dt

from posthog.models.team.team import Team

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.broken import mark_cdc_broken
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import BUFFER_FILE_RETENTION

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

if typing.TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import CDCSourceAdapter
    from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCConfig

BILLING_LIMIT_EXPIRED_REASON = "billing_limit_expired"

_SLOT_DROPPED_MESSAGE = (
    "Change data capture stopped because this team has been over its data warehouse billing limit for "
    "14 days, and PostHog keeps captured changes for 14 days. PostHog dropped the replication slot. "
    "Once you're back under the limit, use Repair CDC to recreate it and re-sync your tables."
)
_SLOT_KEPT_MESSAGE = (
    "Change data capture stopped loading because this team has been over its data warehouse billing "
    "limit for 14 days, and PostHog keeps captured changes for 14 days. The replication slot was not "
    "dropped. Once you're back under the limit, use Repair CDC to re-sync your tables."
)


# Finished job outcomes other than a billing block. A running job has no outcome yet, so it neither
# starts nor ends a billing-blocked run.
_OTHER_OUTCOMES = (
    ExternalDataJob.Status.COMPLETED,
    ExternalDataJob.Status.FAILED,
    ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW,
)


def blocked_past_buffer_retention(source: ExternalDataSource, now: dt.datetime) -> bool:
    """Whether this source's CDC tables have been blocked by the billing limit longer than the buffer keeps changes.

    The team must still be over the limit: once the limit lifts, the tables' next runs load what the
    buffer still holds.
    """
    cdc_schemas = ExternalDataSchema.objects.filter(
        team_id=source.team_id,
        source=source,
        sync_type=ExternalDataSchema.SyncType.CDC,
        should_sync=True,
    ).exclude(deleted=True)
    # A source already marked broken is stopped, and its own recovery path owns the slot.
    if cdc_schemas.filter(sync_type_config__has_key="cdc_broken").exists():
        return False
    cutoff = now - BUFFER_FILE_RETENTION
    blocked = cdc_schemas.filter(status=ExternalDataSchema.Status.BILLING_LIMIT_REACHED)
    # A table blocked that long has not loaded since the cutoff either, so this rules out most tables
    # before any job history is read.
    candidates = [schema for schema in blocked if (schema.last_synced_at or schema.created_at) < cutoff]
    if not any(_blocked_past(source, schema.id, cutoff) for schema in candidates):
        return False
    team = Team.objects.only("api_token").get(id=source.team_id)
    return is_team_limited(team.api_token, QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)


def _blocked_past(source: ExternalDataSource, schema_id: uuid.UUID, cutoff: dt.datetime) -> bool:
    """Whether this table's current run of billing-blocked jobs started before ``cutoff``."""
    blocked_since = _billing_blocked_since(source, schema_id)
    return blocked_since is not None and blocked_since < cutoff


def _billing_blocked_since(source: ExternalDataSource, schema_id: uuid.UUID) -> dt.datetime | None:
    """When this table's current run of billing-blocked jobs began.

    That run starts at the table's first blocked job after its last job with another outcome. Only
    this table's own jobs count — a sibling table can fail, and a non-billable run skips the billing
    check and completes, while this table stays blocked. A table can also go longer without a load for
    other reasons, which is why this is not the time since its last load.
    """
    jobs = ExternalDataJob.objects.filter(team_id=source.team_id, pipeline_id=source.id, schema_id=schema_id)
    # One ordered lookup per status, because the (team, pipeline, status, created_at) index serves an
    # equality on status and not an exclusion.
    latest_by_outcome = [
        jobs.filter(status=outcome).order_by("-created_at").values_list("created_at", flat=True).first()
        for outcome in _OTHER_OUTCOMES
    ]
    last_other = max((created_at for created_at in latest_by_outcome if created_at is not None), default=None)
    blocked = jobs.filter(status=ExternalDataJob.Status.BILLING_LIMIT_REACHED)
    if last_other is not None:
        blocked = blocked.filter(created_at__gt=last_other)
    return blocked.order_by("created_at").values_list("created_at", flat=True).first()


def stop_cdc_past_billing_retention(
    source: ExternalDataSource, cdc_config: CDCConfig, adapter: CDCSourceAdapter[CDCConfig]
) -> bool:
    """Move the source to the broken state, and drop its slot where PostHog may. Returns whether it dropped the slot.

    The slot is dropped on the terms of the lag safety net: only a PostHog-managed slot whose owner
    left auto-drop on. Any other slot is left to its owner, and capture keeps advancing it so the
    customer's WAL does not grow, which is why that case does not pause the schedules.

    Raises when the slot survives the drop, which leaves the source running for the next sweep to
    retry: pausing capture is only safe once nothing has to advance the slot any more.
    """
    if cdc_config.management_mode == "posthog" and cdc_config.auto_drop_slot:
        with adapter.management_connection(source, connect_timeout=10) as conn:
            adapter.drop_resources(conn, cdc_config.slot_name, cdc_config.publication_name)
            # drop_resources is best-effort: it logs a refused drop (an active slot, a missing grant)
            # instead of raising.
            if adapter.slot_exists(conn, cdc_config.slot_name):
                raise RuntimeError(f"Replication slot {cdc_config.slot_name} still exists after the drop")
        mark_cdc_broken(source, BILLING_LIMIT_EXPIRED_REASON, _SLOT_DROPPED_MESSAGE)
        return True
    mark_cdc_broken(source, BILLING_LIMIT_EXPIRED_REASON, _SLOT_KEPT_MESSAGE, pause=False)
    return False
