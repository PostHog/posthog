"""Direct report-authoring write paths for the scout `emit_report` / `edit_report` channel.

See `persistence.py` for the design: an opted-in scout authors a `SignalReport` directly (plus its
backing `document_embeddings` signal rows) instead of routing a weak signal through the grouping
pipeline. This package is the sanctioned write service the harness tools (Phase 3) call — harness
code never touches `SignalReport` or the embeddings pipeline directly.
"""

from products.signals.backend.scout_report.persistence import (
    MAX_REPORT_SIGNALS,
    InvalidScoutReportError,
    PersistedScoutReport,
    ScoutReportSignal,
    append_report_note,
    create_scout_report,
    get_scout_report_title,
    record_report_edit,
    set_scout_report_reviewers,
    soft_delete_scout_signal,
    update_scout_report,
)

__all__ = [
    "MAX_REPORT_SIGNALS",
    "InvalidScoutReportError",
    "PersistedScoutReport",
    "ScoutReportSignal",
    "append_report_note",
    "create_scout_report",
    "get_scout_report_title",
    "record_report_edit",
    "set_scout_report_reviewers",
    "soft_delete_scout_signal",
    "update_scout_report",
]
