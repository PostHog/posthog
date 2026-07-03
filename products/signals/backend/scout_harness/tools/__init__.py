"""Harness-internal tools the Signals agent calls during a run.

The harness wraps these as sync Python functions; the runner / agent-SDK glue
(Phase 3e) is responsible for adapting them into the tool registry seen by the
sandbox. Each tool is team-scoped and Postgres-backed.
"""

from products.signals.backend.scout_harness.tools.emit import (
    MAX_EVIDENCE_ENTRIES,
    MAX_TAG_LENGTH,
    MAX_TAGS_PER_FINDING,
    EmitResult,
    EvidenceEntry,
    InvalidEmitError,
    emit_finding,
    normalize_tags,
)
from products.signals.backend.scout_harness.tools.profile import (
    PROFILE_TTL,
    ProjectProfile,
    compute_project_profile,
    get_project_profile,
)
from products.signals.backend.scout_harness.tools.report import (
    EditReportResult,
    EmitReportResult,
    ReportEvidence,
    StartImplementationResult,
    edit_report,
    edit_report_sync,
    emit_report,
    emit_report_sync,
    start_implementation_sync,
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
    "EditReportResult",
    "EmitReportResult",
    "StartImplementationResult",
    "EmitResult",
    "EvidenceEntry",
    "InvalidEmitError",
    "InvalidScratchpadError",
    "MAX_EVIDENCE_ENTRIES",
    "MAX_RUN_SEARCH_LIMIT",
    "MAX_TAG_LENGTH",
    "MAX_TAGS_PER_FINDING",
    "PROFILE_TTL",
    "ProjectProfile",
    "ReportEvidence",
    "ScratchpadEntry",
    "RunDetail",
    "RunSummary",
    "compute_project_profile",
    "edit_report",
    "edit_report_sync",
    "emit_finding",
    "emit_report",
    "start_implementation_sync",
    "emit_report_sync",
    "forget",
    "get_project_profile",
    "get_run",
    "normalize_tags",
    "remember",
    "search_scratchpad",
    "search_recent_runs",
]
