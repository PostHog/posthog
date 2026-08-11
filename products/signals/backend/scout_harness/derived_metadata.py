"""Harness-observed run dimensions, stamped onto the run row at finalize.

`SignalScoutRun.metadata` holds regions distinguished by who writes them. The top-level
keys are stamped write-once by the runner at run creation (the routed model triple). This
module owns a second region, the nested `derived` object: a flat map of booleans answering
"what kind of run was this?" for the fleet tooling and the `exploring-scouts` reader.

Everything here is computed server-side from what the run already left behind, rather than
self-reported by the scout, because a scout-authored flag is only as reliable as the model
remembering to write it. A derived flag cannot be omitted, misremembered, or contradicted
by the prose close-out, which is what makes `metadata.derived` safe to query directly
instead of parsing `summary`.

The whole map is written at once, so within the region every key is always present. An
absent region is genuinely unknown rather than all-false: the run predates this field, or it
never reached finalize (it failed or was reaped), or its stamp failed and was logged. Consumers
that need to tell those apart have to check the run's status and `created_at`.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from products.signals.backend.models import SignalReport, SignalScoutRun, SignalScratchpad
from products.signals.backend.scout_harness.prompt import FOLLOWUP_KEY_PREFIX
from products.signals.backend.scout_harness.tools.report import is_self_improvement_title
from products.signals.backend.scout_harness.tools.structured_output import STRUCTURED_OUTPUT_COUNT_KEY

logger = logging.getLogger(__name__)

# The sub-object inside `SignalScoutRun.metadata` that harness-derived flags live under.
DERIVED_METADATA_KEY = "derived"

# Every flag `build_derived_flags` writes. The run serializer's schema is built from this, so a
# new flag reaches the generated frontend and MCP types without a second edit that could drift.
DERIVED_FLAG_KEYS = (
    "has_emit_report",
    "has_edit_report",
    "has_self_improvement",
    "has_chart",
    "has_self_validation",
    "has_structured_output",
)


def build_derived_flags(*, run: SignalScoutRun, team_id: int) -> dict[str, bool]:
    """Compute the derived flag map for a finalized run.

    Split out from the write so the classification is testable without a transaction, and so
    a caller that already holds the row can reuse it. `team_id` is passed rather than read off
    the row so every query here is anchored to the canonical team the caller resolved.
    """
    emitted_ids = run.emitted_report_ids or []
    authored_titles, authored_charts = _authored_report_facts(team_id=team_id, report_ids=emitted_ids)
    return {
        "has_emit_report": bool(emitted_ids),
        "has_edit_report": bool(run.edited_report_ids),
        # Both are scoped to reports this run *authored*. A run that edits someone else's
        # self-improvement report, or appends a note to a report whose charts a previous run
        # set, did not itself produce that artefact, so attributing it here would overcount.
        # The trade is that both read the report's state at finalize rather than an immutable
        # emit-time snapshot, so a title or chart set changed after the emit (by this run or a
        # concurrent one) is what gets recorded. The emit-time record lives on the report
        # lifecycle events; these describe the reports the run left behind. The same scoping
        # means charts a run attached to someone else's report through `edit_report` are not
        # counted, which needs run-attributed chart provenance rather than a wider query here.
        "has_self_improvement": any(is_self_improvement_title(title) for title in authored_titles),
        "has_chart": any(charts for charts in authored_charts),
        "has_self_validation": _touched_followup_queue(run=run, team_id=team_id),
        # The record endpoint bumps this counter on the run row under lock, so it's a
        # server-side observation, not a scout self-report. It counts accepted batches —
        # a batch whose event delivery then failed still registers here, which the
        # flood-breaker semantics of the counter accept (see STRUCTURED_OUTPUT_COUNT_KEY).
        "has_structured_output": bool((run.metadata or {}).get(STRUCTURED_OUTPUT_COUNT_KEY)),
    }


def _authored_report_facts(*, team_id: int, report_ids: list[str]) -> tuple[list[str | None], list[Any]]:
    """Titles and chart lists for the reports a run authored, in one query.

    Returns empty lists when the run authored nothing, which keeps the caller free of a
    special case and avoids a query for the common non-emitting run.
    """
    if not report_ids:
        return [], []
    rows = SignalReport.objects.filter(team_id=team_id, id__in=report_ids).values_list("title", "charts")
    titles = [row[0] for row in rows]
    charts = [row[1] for row in rows]
    return titles, charts


def _touched_followup_queue(*, run: SignalScoutRun, team_id: int) -> bool:
    """Whether this run wrote to its own self-validation follow-up queue.

    Working the queue *is* writing to it: the follow-up discipline tells a scout to record the
    validation outcome in each entry it touches, so a `followup:` entry whose `updated_at` falls
    inside the run window is a direct observation of the work rather than a proxy for it.

    The entry must predate the run: an ordinary investigation is told to *create* a follow-up when
    it surfaces something measurable, and a newly created row would otherwise satisfy the window
    and label every such run a validation pass. Requiring `created_at` before the run start keeps
    only writes to a queue that already existed, which is what working the queue means. The
    inverse case stays uncounted: a validation that confirms a fix and then `forget`s the entry
    leaves nothing to observe. That direction under-reports rather than inventing validation runs,
    and the follow-up discipline keeps validated entries around with a `validated` state header
    rather than deleting them, so it should be rare.

    The key prefix is skill-namespaced, and the coordinator's single-flight guard keeps two runs
    of the same `(team, skill)` from overlapping, so the window cannot pick up a sibling's work.
    That guard is best-effort at the app layer, which means a rare overlapping pair could each
    claim the other's queue write. The flag is fleet observability, not an audit trail, so
    tolerating that beats threading run attribution through every scratchpad upsert.

    `for_team` rather than a bare `objects.filter(team_id=...)`: `SignalScratchpad` is fail-closed,
    and finalize runs from a Temporal activity with no request-level team scope installed, so the
    plain manager raises `TeamScopeError` there.
    """
    return (
        SignalScratchpad.objects.for_team(team_id)
        .filter(
            key__startswith=f"{FOLLOWUP_KEY_PREFIX}{run.skill_name}:",
            created_at__lt=run.created_at,
            updated_at__gte=run.created_at,
        )
        .exists()
    )


def stamp_derived_metadata(*, run_id: Any, team_id: int) -> None:
    """Merge the derived flag map into the run's `metadata` under `derived`.

    Best-effort and observability-only: the run's real output has already committed by the time
    this runs, so a failure here is logged rather than surfaced as a run failure. Runs under
    `select_for_update` because the read-modify-write on the JSON column would otherwise race the
    report tally writers, which touch the same row on the same commit path.
    """
    try:
        with transaction.atomic():
            run = SignalScoutRun.objects.for_team(team_id).select_for_update().filter(pk=run_id).first()
            if run is None:
                logger.warning("signals_scout.derived_metadata: run %s gone, skipping stamp", run_id)
                return
            metadata = dict(run.metadata or {})
            metadata[DERIVED_METADATA_KEY] = build_derived_flags(run=run, team_id=team_id)
            run.metadata = metadata
            run.save(update_fields=["metadata"])
    except Exception:
        logger.exception("signals_scout.derived_metadata: failed to stamp derived metadata for run %s", run_id)
