"""Stop CDC on a source whose organization is deactivated.

The table syncs of a deactivated organization stand down before they create a job, but capture is a
separate schedule and keeps reading the slot. The hourly sweep drops a PostHog-managed slot and its
publication and pauses capture, whatever the auto-drop setting, because a deactivated organization
must run nothing. A self-managed slot belongs to the customer: it is kept, and capture keeps advancing
it so the customer's WAL does not grow. The team gets no email, notification or sync alert. After
reactivation, Repair CDC recreates the slot and re-snapshots every table.
"""

from __future__ import annotations

import typing

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.broken import mark_cdc_broken
from products.warehouse_sources.backend.temporal.data_imports.organization_state import ORGANIZATION_DEACTIVATED_REASON

if typing.TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import CDCSourceAdapter
    from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCConfig

_SLOT_DROPPED_MESSAGE = (
    "Change data capture stopped because this organization was deactivated. PostHog dropped the "
    "replication slot. Once the organization is active again, use Repair CDC to recreate it and "
    "re-sync your tables."
)


def stopped_for_deactivation(source: ExternalDataSource) -> bool:
    """Whether an earlier sweep already stopped this source for a deactivated organization.

    Every CDC table must carry the marker. A table added since then, or a marker with another reason,
    means the stop must run again.
    """
    cdc_schemas = ExternalDataSchema.objects.filter(
        team_id=source.team_id,
        source=source,
        sync_type=ExternalDataSchema.SyncType.CDC,
        should_sync=True,
    ).exclude(deleted=True)
    # Counted with a positive filter: `.exclude()` on a JSON key that a table lacks compiles to NOT NULL,
    # which drops that unmarked table from the result instead of keeping it.
    total = cdc_schemas.count()
    stopped = cdc_schemas.filter(sync_type_config__cdc_broken__reason=ORGANIZATION_DEACTIVATED_REASON).count()
    return total > 0 and stopped == total


def stop_cdc_for_deactivated_organization(
    source: ExternalDataSource, cdc_config: CDCConfig, adapter: CDCSourceAdapter[CDCConfig]
) -> bool:
    """Drop a PostHog-managed slot, then move the source to the broken state. Returns whether it stopped capture.

    Returns False for a self-managed slot and changes nothing, so capture keeps advancing it.

    Raises when the slot survives the drop, which leaves the source running for the next sweep to
    retry: pausing capture is only safe once nothing has to advance the slot any more.
    """
    if cdc_config.management_mode != "posthog":
        return False
    with adapter.management_connection(source, connect_timeout=10) as conn:
        adapter.drop_stream(conn, source)
        # drop_stream is best-effort: it logs a refused drop (an active slot, a missing grant)
        # instead of raising.
        if adapter.stream_exists(conn, source):
            raise RuntimeError(f"Replication slot {cdc_config.stream_name} still exists after the drop")
    mark_cdc_broken(source, ORGANIZATION_DEACTIVATED_REASON, _SLOT_DROPPED_MESSAGE, notify=False)
    return True
