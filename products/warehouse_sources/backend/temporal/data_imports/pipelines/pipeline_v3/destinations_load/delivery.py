"""Delivering one batch to every destination configured for the run.

The load consumer calls this after it has written the batch to the PostHog warehouse. All
destinations share one lifecycle: the batch is done only when every one of them has taken it,
and a destination that fails fails the batch, which is then retried in full.

Retrying in full does not mean writing everything again. Each destination has its own
idempotency key, so a retry after Redshift was briefly unreachable skips Snowflake and the
warehouse and writes only what is missing.

The PostHog warehouse is not delivered here. It is written by the delta path in the processor
before this runs, and it carries the unsuffixed idempotency key it has always had.
"""

from __future__ import annotations

from collections.abc import Iterable

import structlog
from asgiref.sync import async_to_sync

from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.registry import resolve_destination_writer
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import build_table_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.builtin_writers import (
    ensure_builtin_destination_writers_registered,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.parquet_source import (
    aiter_record_batches,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.idempotency import (
    is_batch_already_processed,
    mark_batch_as_processed,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import ExportSignalMessage

logger = structlog.get_logger(__name__)


class DestinationDeliveryError(Exception):
    """One destination could not take the batch, so the batch is not done.

    Carries the destination's name so a single job's `latest_error` still says which
    destination stopped the sync.
    """

    def __init__(self, destination_name: str, cause: Exception) -> None:
        self.destination_name = destination_name
        self.cause = cause
        super().__init__(f"{destination_name}: {cause}")


def external_destinations_for(export_signal: ExportSignalMessage) -> list[ExternalDataDestination]:
    """The run's destinations, minus the PostHog warehouse, in a stable order.

    Ordered by id so every batch visits them the same way, which keeps the logs readable
    when a run partially fails and retries.
    """
    if not export_signal.destination_ids:
        return []

    destinations = ExternalDataDestination.objects.for_team(export_signal.team_id, canonical=True).filter(
        id__in=export_signal.destination_ids
    )
    return sorted(
        (d for d in destinations if d.type != ExternalDataDestination.Type.POSTHOG_WAREHOUSE and not d.deleted),
        key=lambda d: str(d.id),
    )


def warehouse_is_a_destination(export_signal: ExportSignalMessage) -> bool:
    """Whether this run writes to the PostHog warehouse at all.

    An empty list means the warehouse only, which is every run that predates destinations.
    A run that lists destinations but not the warehouse never touches delta: the customer
    asked us to move their data somewhere else, not to keep a copy here.
    """
    if not export_signal.destination_ids:
        return True

    return (
        ExternalDataDestination.objects.for_team(export_signal.team_id, canonical=True)
        .filter(
            id__in=export_signal.destination_ids,
            type=ExternalDataDestination.Type.POSTHOG_WAREHOUSE,
            deleted=False,
        )
        .exists()
    )


def destination_table_name(export_signal: ExportSignalMessage, config: dict) -> str:
    """What a destination calls the table for this schema.

    The same name the PostHog warehouse uses, via `build_table_name`, so a table is recognizable
    on both sides and two sources with a same-named resource do not resolve to one table. Falls
    back to the raw resource name only if the schema has gone, which is a run that is failing
    anyway. `table_prefix` stays supported as an escape hatch for a name a customer needs to
    control; nothing sets it today.
    """
    schema = (
        ExternalDataSchema.objects.filter(id=export_signal.schema_id, team_id=export_signal.team_id)
        .select_related("source")
        .first()
    )
    base = build_table_name(schema.source, schema.name) if schema and schema.source else export_signal.resource_name
    return f"{config.get('table_prefix', '')}{base}"


def _run_context(export_signal: ExportSignalMessage, destination: ExternalDataDestination) -> DestinationRunContext:
    config = destination.config or {}
    return DestinationRunContext(
        team_id=export_signal.team_id,
        schema_id=export_signal.schema_id,
        source_id=export_signal.source_id,
        job_id=export_signal.job_id,
        run_uuid=export_signal.run_uuid,
        destination_id=str(destination.id),
        destination_type=destination.type,
        destination_name=destination.name,
        # Derived from the schema, never configured on the destination: a destination is shared
        # by every schema of every source pointed at it, so one configured name would collapse
        # them all into a single table.
        table_name=destination_table_name(export_signal, config),
        sync_type=export_signal.sync_type,
        primary_keys=tuple(export_signal.primary_keys or ()),
        config=config,
        integration_id=destination.integration_id,
    )


def _fail_for_unresolved_destinations(
    export_signal: ExportSignalMessage, resolved: list[ExternalDataDestination]
) -> None:
    """Raise if a destination from the run's snapshot no longer delivers here.

    The only reason a snapshotted id can be absent from `resolved` is that it is the PostHog
    warehouse (delivered elsewhere, exempt here) or that it was deleted after the run started.
    The warehouse case is fine; the deletion case is not — the run's snapshot promised this
    destination the batch, and `external_destinations_for` silently dropping it would let the
    final batch mark the run completed while that destination never received its data. Fail
    the batch instead, the same as any other destination that could not take it.
    """
    resolved_ids = {str(d.id) for d in resolved}
    missing_ids = [
        destination_id for destination_id in export_signal.destination_ids if destination_id not in resolved_ids
    ]
    if not missing_ids:
        return

    missing = ExternalDataDestination.objects.for_team(export_signal.team_id, canonical=True).filter(id__in=missing_ids)
    unresolved = [d for d in missing if d.type != ExternalDataDestination.Type.POSTHOG_WAREHOUSE]
    if not unresolved:
        return

    names = ", ".join(sorted(d.name for d in unresolved))
    raise DestinationDeliveryError(names, LookupError("destination deleted after the run started"))


def deliver_batch_to_destinations(
    export_signal: ExportSignalMessage,
    destinations: Iterable[ExternalDataDestination] | None = None,
) -> int:
    """Write this batch to every external destination that has not already taken it.

    Returns the number of destinations written. Raises `DestinationDeliveryError` on the
    first failure, which fails the batch and leaves it to be retried. That includes a
    destination from the run's snapshot that was deleted mid-run: it is reported as failed
    rather than silently skipped, so the run cannot complete while owing it data.

    Connection hygiene belongs to the caller: `close_old_connections` here would drop the
    connection a caller's transaction is running in, which is what the load consumer already
    does once per message before it gets this far.
    """
    if destinations is not None:
        pending = list(destinations)
    else:
        pending = external_destinations_for(export_signal)
        _fail_for_unresolved_destinations(export_signal, pending)

    if not pending:
        return 0

    written = 0
    for destination in pending:
        destination_id = str(destination.id)

        already_written = is_batch_already_processed(
            export_signal.team_id,
            export_signal.schema_id,
            export_signal.run_uuid,
            export_signal.batch_index,
            destination_id=destination_id,
        )

        # Writing and publishing are separate. The extraction side sends the last batch twice,
        # once while processing and once flagged final, so skipping the whole batch because it
        # was already written would leave a full refresh staged and never swapped in.
        if already_written and not export_signal.is_final_batch:
            logger.debug(
                "destination_batch_already_delivered",
                destination_type=destination.type,
                batch_index=export_signal.batch_index,
            )
            continue

        run_ctx = _run_context(export_signal, destination)
        batch_ctx = DestinationBatchContext(
            run=run_ctx,
            batch_index=export_signal.batch_index,
            is_final_batch=export_signal.is_final_batch,
            expected_row_count=export_signal.row_count,
        )

        try:
            ensure_builtin_destination_writers_registered()
            writer = resolve_destination_writer(run_ctx)
            if not already_written:
                async_to_sync(writer.prepare_run)(run_ctx)
                async_to_sync(_write)(writer, export_signal, batch_ctx)
                # Marked before publication, not after. `finalize_run` is a no-op the second
                # time, but `write_batch` is not: on a full refresh it rebuilds the staging
                # table out of this one batch, so a replay that ran both again would publish
                # that batch over the complete table the first pass swapped in. Marking first
                # makes a replay skip the write and re-run only the idempotent publish.
                mark_batch_as_processed(
                    export_signal.team_id,
                    export_signal.schema_id,
                    export_signal.run_uuid,
                    export_signal.batch_index,
                    destination_id=destination_id,
                )
                written += 1
            if export_signal.is_final_batch:
                async_to_sync(writer.finalize_run)(run_ctx)
        except Exception as e:
            logger.warning(
                "destination_batch_failed",
                destination_type=destination.type,
                batch_index=export_signal.batch_index,
                error=str(e),
            )
            raise DestinationDeliveryError(destination.name, e) from e

        logger.debug(
            "destination_batch_delivered",
            destination_type=destination.type,
            batch_index=export_signal.batch_index,
        )

    return written


async def _write(writer, export_signal: ExportSignalMessage, batch_ctx: DestinationBatchContext) -> None:
    """Stream the staged parquet into the writer a row group at a time.

    Re-read per destination rather than held once: a staged batch targets around 200 MiB of
    Arrow, and holding it for the whole loop would multiply that by the destination count.
    """
    await writer.write_batch(aiter_record_batches(export_signal.s3_path), batch_ctx)


def abort_destinations(export_signal: ExportSignalMessage) -> None:
    """Let each writer drop what a run that will not finish left staged."""
    for destination in external_destinations_for(export_signal):
        run_ctx = _run_context(export_signal, destination)
        try:
            ensure_builtin_destination_writers_registered()
            writer = resolve_destination_writer(run_ctx)
            async_to_sync(writer.abort_run)(run_ctx)
        except Exception as e:
            # Best effort: the next run stages under its own id, so a leftover staging
            # table costs storage rather than correctness.
            logger.warning("destination_abort_failed", destination_type=destination.type, error=str(e))
