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
from products.signals.backend.scout_harness.tools.reports import (
    MAX_REPORTS_PER_RUN,
    InvalidReportWriteError,
    ReportNotFoundError,
    ReportWriteResult,
    create_report_sync,
    update_report_sync,
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
    "InvalidReportWriteError",
    "InvalidScratchpadError",
    "MAX_EVIDENCE_ENTRIES",
    "MAX_REPORTS_PER_RUN",
    "MAX_RUN_SEARCH_LIMIT",
    "MAX_TAG_LENGTH",
    "MAX_TAGS_PER_FINDING",
    "PROFILE_TTL",
    "ProjectProfile",
    "ReportNotFoundError",
    "ReportWriteResult",
    "ScratchpadEntry",
    "RunDetail",
    "RunSummary",
    "compute_project_profile",
    "create_report_sync",
    "emit_finding",
    "forget",
    "get_project_profile",
    "get_run",
    "normalize_tags",
    "remember",
    "search_scratchpad",
    "search_recent_runs",
    "update_report_sync",
]
