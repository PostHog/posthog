"""Stop CDC on a source whose team stays over the billing limit for longer than the buffer keeps changes.

Capture has no billing check: it keeps reading the slot and writing the buffer while the limit blocks
every load. Once a blocked table's oldest unread change is older than the buffer retention, the
lifecycle rule starts deleting changes the table never loaded, so only a re-snapshot can make it
correct again. From then on the slot costs the customer WAL and the buffer costs storage for data
that will never load. The source moves to the broken state, and Repair CDC re-snapshots every table
once the team is back under the limit.
"""

from __future__ import annotations

import typing
import datetime as dt

from posthog.models.team.team import Team

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


def blocked_past_buffer_retention(source: ExternalDataSource, now: dt.datetime) -> bool:
    """Whether a CDC table of this source has been blocked by the billing limit longer than the buffer keeps changes.

    A table's first unread change was written just after its last load, so its age is the time since
    that load. The team must still be over the limit: once the limit lifts, the table's next run loads
    what the buffer still holds.
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
    if not any((schema.last_synced_at or schema.created_at) < cutoff for schema in blocked):
        return False
    team = Team.objects.only("api_token").get(id=source.team_id)
    return is_team_limited(team.api_token, QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)


def stop_cdc_past_billing_retention(
    source: ExternalDataSource, cdc_config: CDCConfig, adapter: CDCSourceAdapter[CDCConfig]
) -> bool:
    """Move the source to the broken state, and drop its slot where PostHog may. Returns whether it dropped the slot.

    The slot is dropped on the terms of the lag safety net: only a PostHog-managed slot whose owner
    left auto-drop on. Any other slot is left to its owner, and capture keeps advancing it so the
    customer's WAL does not grow, which is why that case does not pause the schedules.
    """
    if cdc_config.management_mode == "posthog" and cdc_config.auto_drop_slot:
        with adapter.management_connection(source, connect_timeout=10) as conn:
            adapter.drop_resources(conn, cdc_config.slot_name, cdc_config.publication_name)
        mark_cdc_broken(source, BILLING_LIMIT_EXPIRED_REASON, _SLOT_DROPPED_MESSAGE)
        return True
    mark_cdc_broken(source, BILLING_LIMIT_EXPIRED_REASON, _SLOT_KEPT_MESSAGE, pause=False)
    return False
