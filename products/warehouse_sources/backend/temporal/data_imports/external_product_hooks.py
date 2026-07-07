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
