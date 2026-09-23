"""Automatic reset-and-resync for safe numeric column-type widenings.

delta-rs cannot widen a column in place, so the only remedy for a source column widened upstream is
a reset and full re-sync. Without automation that failure is permanent until a human clicks "Reset":
the v3 load consumer fails the run but never pauses the schema, so the same doomed sync repeats on
every schedule. When the failed transition is a safe numeric widening (see
``is_safe_numeric_widening``), ``maybe_schedule_auto_widen_resync`` stamps ``reset_pipeline`` on the
schema so the next scheduled sync performs exactly the reset the manual button would, plus a
``column_type_widened`` marker for observability, the reset cooldown, and health-check muting.

The stamp must happen at failure time and the reset on the *next* run, never mid-run: the
incremental watermark and the source's extraction query are resolved at the top of
``import_data_sync`` before the pipeline runs, so wiping the table inside the failing run would
rebuild it from only the rows past the old watermark.

Gated per schema by the ``data-warehouse-auto-widen-resync`` flag (fail closed). Killing the flag
stops new stamps; a reset already stamped still runs, since ``reset_pipeline`` is the same
mechanism manual resets use and cannot be gated at consumption.
"""

import datetime as dt
from typing import TYPE_CHECKING, Any

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.utils import get_machine_id

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    SchemaColumnTypeChangedException,
    is_safe_numeric_widening,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)

WAREHOUSE_AUTO_WIDEN_RESYNC_FLAG = "data-warehouse-auto-widen-resync"

# At most one automatic reset per schema per window; a second widening inside it falls back to the
# manual reset flow. Guards against a source that flip-flops types re-reading its entire table on
# every scheduled sync.
AUTO_WIDEN_RESYNC_COOLDOWN = dt.timedelta(days=7)

COLUMN_TYPE_WIDENED_KEY = "column_type_widened"
# Kept separately from the marker (and never popped by the reset) so the cooldown survives the
# reset that consumes the marker.
COLUMN_TYPE_WIDENED_LAST_RESET_AT_KEY = "column_type_widened_last_reset_at"


def is_auto_widen_resync_enabled(team_id: int, schema_id: str, source_type: str | None = None) -> bool:
    """Evaluate the per-schema auto-widen-resync rollout flag.

    ``schema_id`` / ``team_id`` / ``source_type`` are passed as person properties so the flag can be
    released to a single table first (release condition ``schema_id = <id>``) before ramping by team /
    org / source. Mirrors ``is_deltalite_write_enabled``. This flag is the only control (no env
    switch), so recovery can be ramped or killed from the flag UI without a deploy. Any evaluation
    failure returns False (fail closed): a flags-service blip must never accidentally switch it on.
    """
    from posthog.models import Team  # noqa: PLC0415 to keep the Django model off this pipeline module's import path

    try:
        team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    except Team.DoesNotExist:
        return False

    person_properties: dict[str, str] = {"schema_id": str(schema_id), "team_id": str(team_id)}
    if source_type is not None:
        person_properties["source_type"] = source_type

    try:
        return bool(
            posthoganalytics.feature_enabled(
                WAREHOUSE_AUTO_WIDEN_RESYNC_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team_id)},
                person_properties=person_properties,
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team_id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def maybe_schedule_auto_widen_resync(
    schema: "ExternalDataSchema", job: "ExternalDataJob", error: SchemaColumnTypeChangedException
) -> str | None:
    """Schedule an automatic reset-and-resync for a safe numeric widening failure.

    Returns the customer-facing message the failed run should surface instead of the manual-reset
    instruction when the resync was scheduled, and None otherwise (unsafe transition, flag off,
    cooldown active, CDC streaming or webhook schema, or any internal failure). Best-effort by contract: this
    runs inside the load consumer's failure path, so it must never raise; the original error is
    re-raised by the caller either way.
    """
    try:
        return _schedule_auto_widen_resync(schema, job, error)
    except Exception as e:
        capture_exception(e)
        logger.exception(
            "auto_widen_resync_scheduling_failed",
            external_data_schema_id=str(schema.id),
            team_id=schema.team_id,
        )
        return None


def _schedule_auto_widen_resync(
    schema: "ExternalDataSchema", job: "ExternalDataJob", error: SchemaColumnTypeChangedException
) -> str | None:
    from products.warehouse_sources.backend.models.external_data_schema import (  # noqa: PLC0415 to keep the Django model off this pipeline module's import path
        update_sync_type_config_keys,
    )

    column = error.column_name
    stored_type = error.stored_type
    incoming_type = error.incoming_type
    if column is None or stored_type is None or incoming_type is None:
        return None
    if not is_safe_numeric_widening(stored_type, incoming_type):
        return None
    # A streaming-mode CDC schema has its per-schema schedule paused (CDCExtractionWorkflow owns
    # it), so a stamped reset would never run; leave it to the manual repair flow.
    if schema.is_cdc and schema.cdc_mode == "streaming":
        return None
    # A webhook-only resource consumes reset_pipeline without wiping the table (its rows can't be
    # rebuilt from a poll; see handle_reset_or_full_refresh), so a stamp would promise a re-sync
    # that never happens. Whether the resource is webhook-only isn't knowable here, so skip every
    # webhook-mode schema conservatively.
    if schema.is_webhook:
        return None

    source_type = schema.source.source_type if schema.source else None
    if not is_auto_widen_resync_enabled(schema.team_id, str(schema.id), source_type=source_type):
        return None

    now = dt.datetime.now(dt.UTC)
    stamped = False

    def _stamp_if_out_of_cooldown(config: dict[str, Any]) -> None:
        nonlocal stamped
        if _within_cooldown(config, now):
            return
        config["reset_pipeline"] = True
        config[COLUMN_TYPE_WIDENED_KEY] = {
            "column": column,
            "stored_type": str(stored_type),
            "incoming_type": str(incoming_type),
            "detected_at": now.isoformat(),
        }
        config[COLUMN_TYPE_WIDENED_LAST_RESET_AT_KEY] = now.isoformat()
        stamped = True

    # The cooldown check must read the freshest config, so it runs inside the row lock: two load
    # consumers failing batches of the same schema concurrently would otherwise both pass a
    # read-then-write check.
    schema.sync_type_config = update_sync_type_config_keys(schema.id, schema.team_id, mutate=_stamp_if_out_of_cooldown)

    outcome = "scheduled" if stamped else "cooldown_blocked"
    _capture_auto_widen_resync(
        schema,
        job,
        column=column,
        stored_type=str(stored_type),
        incoming_type=str(incoming_type),
        outcome=outcome,
    )
    logger.info(
        "auto_widen_resync_" + outcome,
        external_data_schema_id=str(schema.id),
        team_id=schema.team_id,
        column=column,
        stored_type=str(stored_type),
        incoming_type=str(incoming_type),
    )

    if not stamped:
        return None
    # Keep the "Source column type changed" prefix: the consumer's non-retryable and
    # expected-user-error classification substring-matches it.
    return (
        f"Source column type changed: '{column}' has values that no longer fit its stored type "
        f"{stored_type} (incoming data is now {incoming_type}). This table will be reset and fully "
        f"re-synced automatically at the next scheduled sync. No action is needed."
    )


def _within_cooldown(config: dict[str, Any], now: dt.datetime) -> bool:
    last_reset_raw = config.get(COLUMN_TYPE_WIDENED_LAST_RESET_AT_KEY)
    if not isinstance(last_reset_raw, str):
        return False
    try:
        last_reset = dt.datetime.fromisoformat(last_reset_raw)
    except ValueError:
        return False
    return now - last_reset < AUTO_WIDEN_RESYNC_COOLDOWN


def _capture_auto_widen_resync(
    schema: "ExternalDataSchema",
    job: "ExternalDataJob",
    *,
    column: str,
    stored_type: str,
    incoming_type: str,
    outcome: str,
) -> None:
    """Emit a `warehouse_auto_widen_resync` event so automatic recoveries are observable (how many
    are scheduled vs blocked by the cooldown, and which transitions occur). Best-effort: it must
    never block the failure path."""
    try:
        posthoganalytics.capture(
            distinct_id=get_machine_id(),
            event="warehouse_auto_widen_resync",
            properties={
                "team_id": schema.team_id,
                "schema_id": str(schema.id),
                "source_id": str(schema.source_id),
                "resource_name": schema.name,
                "job_id": str(job.id),
                "column": column,
                "stored_type": stored_type,
                "incoming_type": incoming_type,
                "outcome": outcome,
            },
        )
    except Exception as e:
        capture_exception(e)
