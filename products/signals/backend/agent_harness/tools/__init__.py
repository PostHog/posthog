"""Harness-internal tools the Signals agent calls during a run.

The harness wraps these as sync Python functions; the runner / agent-SDK glue
(Phase 3e) is responsible for adapting them into the tool registry seen by the
sandbox. Each tool is team-scoped and Postgres-backed.
"""

from products.signals.backend.agent_harness.tools.emit import (
    MAX_EVIDENCE_ENTRIES,
    EmitResult,
    EvidenceEntry,
    InvalidEmitError,
    emit_finding,
)
from products.signals.backend.agent_harness.tools.memory import (
    DEFAULT_MEMORY_TTL_DAYS,
    MAX_MEMORY_TTL_DAYS,
    HumanConfirmedMemoryError,
    InvalidMemoryError,
    MemoryEntry,
    forget,
    remember,
    search_memory,
)
from products.signals.backend.agent_harness.tools.runs import (
    DEFAULT_RUN_SEARCH_LIMIT,
    MAX_RUN_SEARCH_LIMIT,
    RunDetail,
    RunSummary,
    get_run,
    search_recent_runs,
)

__all__ = [
    "DEFAULT_MEMORY_TTL_DAYS",
    "DEFAULT_RUN_SEARCH_LIMIT",
    "EmitResult",
    "EvidenceEntry",
    "HumanConfirmedMemoryError",
    "InvalidEmitError",
    "InvalidMemoryError",
    "MAX_EVIDENCE_ENTRIES",
    "MAX_MEMORY_TTL_DAYS",
    "MAX_RUN_SEARCH_LIMIT",
    "MemoryEntry",
    "RunDetail",
    "RunSummary",
    "emit_finding",
    "forget",
    "get_run",
    "remember",
    "search_memory",
    "search_recent_runs",
]
