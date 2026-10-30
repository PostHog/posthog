"""The part of a CDC-capable source that does not depend on its database engine."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import (
    get_cdc_adapter,
    source_type_supports_cdc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ConfigType, _BaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

log = logging.getLogger(__name__)


class CDCSourceMixin(_BaseSource[ConfigType]):
    """Change data capture for a source whose engine has an adapter in `cdc/adapters.py`.

    The engine specifics stay behind the adapter, so a new engine implements only
    `check_cdc_prerequisites` here. Subclassing `_BaseSource` puts these hooks ahead of its no-op
    defaults in every source's method resolution order, whatever the order of the bases.
    """

    def check_cdc_prerequisites(
        self,
        config: ConfigType,
        management_mode: str,
        tables: list[str],
        setup: Mapping[str, Any],
        require_ssl: bool = True,
        team_id: int | None = None,
    ) -> list[str]:
        """Validate the CDC prerequisites against a live connection, before the source exists.

        ``setup`` holds the engine's own ``cdc_*`` setup fields from the request. Returns one
        message per unmet prerequisite.
        """
        raise NotImplementedError(f"{type(self).__name__} does not check CDC prerequisites")

    def cleanup_cdc_resources_on_deletion(self, source: ExternalDataSource) -> None:
        """Drop the Temporal schedule + PostHog-managed slot/publication.

        Schedule lives on our side, slot lives on the customer's DB. No-op for
        sources without CDC enabled.
        """
        # A source type with no adapter can never have enabled CDC.
        if not source_type_supports_cdc(source.source_type):
            return
        adapter = get_cdc_adapter(source)
        cdc_config = adapter.parse_cdc_config(source)
        if not cdc_config.enabled:
            return

        # Lazy: data_load.service pulls in Temporal client / Celery setup we don't want at module load.
        from products.data_warehouse.backend.facade.api import delete_cdc_extraction_schedule

        # Schedule key = source id. NotFound is a no-op.
        try:
            delete_cdc_extraction_schedule(str(source.id))
        except Exception:
            log.exception("Failed to delete CDC extraction schedule", extra={"source_id": str(source.id)})

        if cdc_config.management_mode != "posthog":
            return
        if not cdc_config.stream_resources_configured:
            return

        try:
            with adapter.management_connection(source, connect_timeout=10) as conn:
                adapter.drop_stream(conn, source)
        except Exception:
            log.exception(
                "Failed to drop CDC slot/publication on source DB (best-effort)",
                extra={"source_id": str(source.id), "slot_name": cdc_config.stream_name},
            )

    def _buffered_cdc_source(self, schema: ExternalDataSchema, inputs: SourceInputs) -> SourceResponse:
        """A `SourceResponse` reading this streaming, seeded schema's S3 change buffer."""
        from asgiref.sync import async_to_sync

        from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
        from products.warehouse_sources.backend.temporal.data_imports.cdc.companion_jobs import (
            retire_orphaned_companions,
        )
        from products.warehouse_sources.backend.temporal.data_imports.cdc.history_table import kept_history_naming
        from products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane import hand_reset_to_capture
        from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import (
            CDCSourceManager,
            buffer_expired_unread,
            build_output_lanes,
            clear_listing,
            completed_listing_proof,
            has_batches_in_flight,
            served_lanes,
        )

        history = kept_history_naming(schema)
        if not served_lanes(schema, history):
            raise ValueError(
                f"CDC schema {schema.name} has cdc_table_mode {schema.cdc_table_mode!r}, which no buffer lane "
                "writes. Set it to 'consolidated', 'cdc_only' or 'both'."
            )

        def no_op_tick(*, reset_handed_over: bool = False) -> SourceResponse:
            # An empty response no-ops this tick and keeps the schedule alive. Nothing is listed and
            # nothing is deleted. An earlier attempt of this same job may have stamped a listing, though, and
            # the workflow completes the job on this response — so the stamp comes off, or a batch
            # of that attempt failing later would leave a Completed job proving a listing nothing
            # drained.
            clear_listing(inputs.job_id, inputs.team_id)
            first_lane = served_lanes(schema, history)[0]
            return SourceResponse(
                name=first_lane.resource_name,
                items=lambda: iter(()),
                primary_keys=schema.primary_key_columns,
                cdc_write_mode=first_lane.write_mode,
                # A change stream carries no seekable key, and `supports_resume` defaults to True.
                supports_resume=False,
                reset_handed_over=reset_handed_over,
            )

        job = ExternalDataJob.objects.filter(id=inputs.job_id, team_id=inputs.team_id).first()

        # A CDC reset must travel through snapshot mode, which re-seeds the table before the buffer
        # replays over it. Merging the buffer into a wiped table instead would leave only the rows
        # changed since. A reset that reaches a streaming table anyway goes to capture, which puts the
        # table back into snapshot mode. Refusing it would fail every run of the table until a manual reset.
        # This run must not delete the table itself: capture waits for queued batches to land first.
        if inputs.reset_pipeline:
            inputs.logger.warning("cdc_buffered_reset_handed_to_capture", schema_name=schema.name)
            hand_reset_to_capture(schema, inputs.logger, start_capture=False)
            return no_op_tick(reset_handed_over=True)

        if has_batches_in_flight(schema):
            # Reading now would stage rows alongside a delivery that is still landing: a previous
            # attempt of this job holds staged batches that are still claimable, which the append
            # lane would then write twice.
            inputs.logger.info("cdc_buffered_waiting_for_in_flight_batches", schema_name=schema.name)
            return no_op_tick()

        if job is None:
            raise ValueError(f"Buffered CDC schema {schema.name} has no job row for run {inputs.job_id}")

        proof = async_to_sync(completed_listing_proof)(schema)
        # The bucket deletes a buffer file once it is older than BUFFER_FILE_RETENTION. A table that has
        # consumed nothing for longer may have lost changes it never loaded, so reading on would leave it
        # wrong for good, and only a re-snapshot makes it correct. Capture does the reset once this run
        # has finished, as it does for any reset a sync could interfere with. A recent proof settles it
        # without the longer read.
        if proof is None and async_to_sync(buffer_expired_unread)(schema):
            inputs.logger.warning(
                "cdc_buffer_expired_before_consumption", schema_name=schema.name, last_synced_at=schema.last_synced_at
            )
            hand_reset_to_capture(schema, inputs.logger, start_capture=False)
            return no_op_tick()

        # Nothing of any earlier run is executing now, so a companion still Running belongs to a
        # run that died without its `finally` and nothing else will ever close it.
        retired = retire_orphaned_companions(schema)
        if retired:
            inputs.logger.warning("cdc_orphaned_companion_jobs_retired", schema_name=schema.name, job_ids=retired)

        # Every table this schema's changes feed, written from one read of the buffer. Each lane
        # carries where its own table stops, because a failed run can leave one ahead of the other.
        lanes, deletion_floor = async_to_sync(build_output_lanes)(schema, job, inputs.logger, history)
        manager = CDCSourceManager(
            inputs,
            inputs.logger,
            deletion_floor=deletion_floor,
            proof=proof,
        )
        return SourceResponse(
            name=lanes[0].name,
            items=manager.get_items,
            primary_keys=schema.primary_key_columns,
            cdc_write_mode=lanes[0].cdc_write_mode,
            lanes=lanes,
            # A change stream reads a buffer, not a keyed table, so there is no key to seek past.
            supports_resume=False,
        )
