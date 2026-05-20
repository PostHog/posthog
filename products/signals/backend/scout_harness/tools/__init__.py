"""Harness-internal tools the Signals agent calls during a run.

The harness wraps these as sync Python functions; the runner / agent-SDK glue
(Phase 3e) is responsible for adapting them into the tool registry seen by the
sandbox. Each tool is team-scoped and Postgres-backed.
"""

from products.signals.backend.scout_harness.tools.emit import (
    MAX_EVIDENCE_ENTRIES,
    EmitResult,
    EvidenceEntry,
    InvalidEmitError,
    emit_finding,
)
from products.signals.backend.scout_harness.tools.runs import (
    DEFAULT_RUN_SEARCH_LIMIT,
    MAX_RUN_SEARCH_LIMIT,
    RunDetail,
    RunSummary,
    get_run,
    search_recent_runs,
)
from products.signals.backend.scout_harness.tools.scratchpad import (
    InvalidScratchpadError,
    ScratchpadEntry,
    forget,
    remember,
    search_scratchpad,
)

__all__ = [
    "DEFAULT_RUN_SEARCH_LIMIT",
    "EmitResult",
    "EvidenceEntry",
    "InvalidEmitError",
    "InvalidScratchpadError",
    "MAX_EVIDENCE_ENTRIES",
    "MAX_RUN_SEARCH_LIMIT",
    "ScratchpadEntry",
    "RunDetail",
    "RunSummary",
    "emit_finding",
    "forget",
    "get_run",
    "remember",
    "search_scratchpad",
    "search_recent_runs",
]
