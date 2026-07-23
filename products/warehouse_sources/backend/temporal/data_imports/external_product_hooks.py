"""Inversion hooks and trigger contracts that let the data-import pipeline drive
work owned by *other* products (signals, revenue analytics) without importing
them.

Both the signals and revenue_analytics products depend on warehouse_sources, so a
direct import from here would create a dependency cycle. Instead each product
registers its implementation at app-ready time (see its AppConfig.ready()), and the
pipeline calls through the registered callable. When nothing is registered the
pipeline degrades to a no-op, which keeps warehouse_sources importable on its own.
"""

import uuid
import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


# --- Signal emission trigger contract -------------------------------------------------
# The payload the import workflow sends to the signals child workflow. It lives here (not
# in the signals product) so the workflow can construct it without importing signals; the
# signals product imports it downward (signals -> warehouse_sources), which is allowed.


@dataclasses.dataclass(frozen=True)
class EmitSignalsActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    job_id: str
    source_type: str
    schema_name: str
    # ISO timestamp of when the previous sync completed.
    # Used to filter records with partition_field > last_synced_at.
    last_synced_at: str | None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "job_id": self.job_id,
            "source_type": self.source_type,
            "schema_name": self.schema_name,
        }


# --- Signal-emission gate -------------------------------------------------------------
# (team_id, source_type, schema_name, ai_data_processing_approved) -> should emit signals
EmitSignalsGate = Callable[[int, str, str, bool], bool]
_emit_signals_gate: Optional[EmitSignalsGate] = None


def register_emit_signals_gate(fn: EmitSignalsGate) -> None:
    global _emit_signals_gate
    _emit_signals_gate = fn


def emit_signals_enabled_for(
    team_id: int, source_type: str, schema_name: str, ai_data_processing_approved: bool
) -> bool:
    if _emit_signals_gate is None:
        return False
    return _emit_signals_gate(team_id, source_type, schema_name, ai_data_processing_approved)


# --- Revenue-analytics view sync ------------------------------------------------------
RevenueViewSync = Callable[["ExternalDataSchema", "ExternalDataSource"], None]
_revenue_view_sync: Optional[RevenueViewSync] = None


def register_revenue_view_sync(fn: RevenueViewSync) -> None:
    global _revenue_view_sync
    _revenue_view_sync = fn


def run_revenue_view_sync(schema: "ExternalDataSchema", source: "ExternalDataSource") -> None:
    if _revenue_view_sync is None:
        return
    _revenue_view_sync(schema, source)


# --- Engineering-analytics view sync --------------------------------------------------
EngineeringAnalyticsViewSync = Callable[["ExternalDataSchema", "ExternalDataSource"], None]
_engineering_analytics_view_sync: Optional[EngineeringAnalyticsViewSync] = None


def register_engineering_analytics_view_sync(fn: EngineeringAnalyticsViewSync) -> None:
    global _engineering_analytics_view_sync
    _engineering_analytics_view_sync = fn


def run_engineering_analytics_view_sync(schema: "ExternalDataSchema", source: "ExternalDataSource") -> None:
    if _engineering_analytics_view_sync is None:
        return
    _engineering_analytics_view_sync(schema, source)


# --- Person-property staging projection -----------------------------------------------
# Person-target Customer analytics sources stage a projection of each synced chunk to S3 so a
# post-sync job can upsert warehouse columns onto person properties. The pipeline asks this hook
# which columns to stage for a schema; each enabled person source contributes its key (the person
# identifier) plus its mapped property columns. Key columns are tracked separately from mapped
# columns so the sink never stages property values with no person identifier to attach them to.
# The hook returns None when nothing needs staging. customer_analytics registers the resolver at
# app-ready; when nothing is registered this returns None and the pipeline stages nothing, so
# warehouse_sources stays importable on its own.


@dataclasses.dataclass(frozen=True)
class PersonPropertySourceProjection:
    """One person-target source's staging projection: its key column (the person identifier) and
    the warehouse columns to stage for it (the key plus its mapped property columns)."""

    key_column: str
    columns: frozenset[str]


PersonPropertyProjectionResolver = Callable[[int, "str | uuid.UUID"], Optional[list[PersonPropertySourceProjection]]]
_person_property_projection_resolver: Optional[PersonPropertyProjectionResolver] = None


def register_person_property_projection(fn: PersonPropertyProjectionResolver) -> None:
    global _person_property_projection_resolver
    _person_property_projection_resolver = fn


def person_property_projection_for(
    team_id: int, schema_id: "str | uuid.UUID"
) -> Optional[list[PersonPropertySourceProjection]]:
    if _person_property_projection_resolver is None:
        return None
    return _person_property_projection_resolver(team_id, schema_id)


def person_property_sync_enabled_for(team_id: int, schema_id: "uuid.UUID") -> bool:
    """Gate for starting the person-property sync child workflow: true when the schema feeds at
    least one enabled person-target source (i.e. there are columns to stage/upsert)."""
    return person_property_projection_for(team_id, schema_id) is not None


@dataclasses.dataclass(frozen=True)
class PersonPropertySyncSource:
    """One enabled person-target source's sync config, resolved through the hook below so the
    sync job (owned by warehouse_sources) never imports the customer_analytics config models.
    ``source_id``/``definition_id`` identify the source for provenance stamping; ``key_column``
    holds the person identifier and ``column_property_map`` maps warehouse column -> person
    property name."""

    source_id: str
    definition_id: str
    key_column: str
    column_property_map: dict[str, str]


PersonPropertySyncSourcesResolver = Callable[[int, "str | uuid.UUID"], Optional[list[PersonPropertySyncSource]]]
_person_property_sync_sources_resolver: Optional[PersonPropertySyncSourcesResolver] = None


def register_person_property_sync_sources(fn: PersonPropertySyncSourcesResolver) -> None:
    global _person_property_sync_sources_resolver
    _person_property_sync_sources_resolver = fn


def person_property_sync_sources_for(
    team_id: int, schema_id: "str | uuid.UUID"
) -> Optional[list[PersonPropertySyncSource]]:
    if _person_property_sync_sources_resolver is None:
        return None
    return _person_property_sync_sources_resolver(team_id, schema_id)


@dataclasses.dataclass(frozen=True)
class PersonPropertySyncActivityInputs:
    """Payload the import workflow sends to the person-property sync child workflow."""

    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    job_id: str
    source_type: str
    schema_name: str
    last_synced_at: str | None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "schema_id": str(self.schema_id),
            "source_id": str(self.source_id),
            "job_id": self.job_id,
            "source_type": self.source_type,
            "schema_name": self.schema_name,
        }


# --- Person-property backfill trigger contract ----------------------------------------
# A backfill reads a warehouse table's full Delta data from S3 (rather than the incrementally
# staged rows) to populate historical rows a new/changed person mapping never saw. It is keyed by
# schema, not source: one backfill workflow reads the table once and upserts every enabled person
# source on it.


@dataclasses.dataclass(frozen=True)
class PersonPropertyBackfillActivityInputs:
    """Payload for the person-property backfill workflow (see person_property_backfill_job.py)."""

    team_id: int
    schema_id: uuid.UUID
    source_type: str
    schema_name: str
    # "backfill" (auto on create/enable) or "manual" (a user asked to re-run). Recorded on the run.
    trigger: str

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "schema_id": str(self.schema_id),
            "source_type": self.source_type,
            "schema_name": self.schema_name,
            "trigger": self.trigger,
        }


# --- Person-property sync run recorder ------------------------------------------------
# The sync/backfill activities (owned by warehouse_sources) persist each run's funnel counts so the
# customer_analytics UI can show run history and affected-person counts. Recording is inverted the
# same way as the resolvers above: customer_analytics registers a recorder at app-ready that writes
# the CustomPropertySyncRun row (and updates the source's status fields); when nothing is registered
# this is a no-op, so warehouse_sources stays importable and a bookkeeping failure never blocks a sync.


@dataclasses.dataclass(frozen=True)
class PersonPropertySyncRunRecord:
    """One source's run outcome. Timestamps are ISO strings so the record crosses the hook boundary
    without timezone/serialization surprises."""

    team_id: int
    schema_id: str
    source_id: str
    job_id: str | None
    trigger: str
    status: str
    started_at: str
    finished_at: str
    rows_read: int
    changed: int
    existing: int
    produced: int
    skipped_missing_person: int
    error: str | None


PersonPropertySyncRecorder = Callable[[PersonPropertySyncRunRecord], None]
_person_property_sync_recorder: Optional[PersonPropertySyncRecorder] = None


def register_person_property_sync_recorder(fn: PersonPropertySyncRecorder) -> None:
    global _person_property_sync_recorder
    _person_property_sync_recorder = fn


def record_person_property_sync_run(record: PersonPropertySyncRunRecord) -> None:
    if _person_property_sync_recorder is None:
        return
    _person_property_sync_recorder(record)
