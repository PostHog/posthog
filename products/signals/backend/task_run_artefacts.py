"""Helpers for appending and querying `task_run` log artefacts on a report.

A `task_run` artefact records that a `tasks.Task` ran for a report (research, implementation,
repo-selection, …) so the run shows up in the report's work-log timeline. The append lives here
as a single source of truth, shared by the live creation paths and the
`backfill_task_run_artefacts` management command.

Each artefact carries a `(product, type)` pair following the custom-agent identifier shape: the
built-in signals pipeline uses `product="signals"` with one of the `TASK_RUN_TYPE_*` constants
as `type`; custom agents supply their own `identifier()` pair. The pair is also how a task's
purpose is *derived* — there is no relationship label on the task↔report association itself.
"""

from __future__ import annotations

from products.signals.backend.artefact_schemas import (
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_IMPLEMENTATION,
    TASK_RUN_TYPE_REPO_SELECTION,
    TASK_RUN_TYPE_RESEARCH,
    TaskRunArtefact,
)
from products.signals.backend.billing import mark_report_billing_exempt
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalReportTask

# The task-run vocabulary lives in `artefact_schemas` (a leaf module the model layer can import
# without a cycle); re-exported here so existing `from task_run_artefacts import …` callers keep
# working.
__all__ = [
    "SIGNALS_PRODUCT",
    "TASK_RUN_TYPE_IMPLEMENTATION",
    "TASK_RUN_TYPE_REPO_SELECTION",
    "TASK_RUN_TYPE_RESEARCH",
    "aappend_task_run_artefact",
    "append_task_run_artefact",
    "record_implementation_task",
    "signals_task_ids",
]


def _task_run_content(product: str, type: str, task_id: str, run_id: str | None) -> TaskRunArtefact:
    return TaskRunArtefact(
        task_id=str(task_id),
        run_id=str(run_id) if run_id is not None else None,
        product=product,
        type=type,
    )


def append_task_run_artefact(
    *, team_id: int, report_id: str, product: str, type: str, task_id: str, run_id: str | None = None
) -> SignalReportArtefact:
    """Append a `task_run` log artefact recording that a task ran for the report (sync).

    Always attributed to the task it records — that task *is* the producer of the entry.
    """
    return SignalReportArtefact.add_log(
        team_id=team_id,
        report_id=str(report_id),
        content=_task_run_content(product, type, task_id, run_id),
        attribution=ArtefactAttribution.from_task(task_id),
    )


async def aappend_task_run_artefact(
    *, team_id: int, report_id: str, product: str, type: str, task_id: str, run_id: str | None = None
) -> SignalReportArtefact:
    """Append a `task_run` log artefact recording that a task ran for the report (async).

    Uses the async ORM directly (not a `database_sync_to_async` hop, which would run on a
    different connection and not see the caller's uncommitted rows); content validation and
    task attribution match `append_task_run_artefact`.
    """
    return await SignalReportArtefact.objects.acreate(
        team_id=team_id,
        report_id=str(report_id),
        type=SignalReportArtefact.ArtefactType.TASK_RUN,
        content=_task_run_content(product, type, task_id, run_id).model_dump_json(),
        task_id=str(task_id),
    )


def signals_task_ids(*, report_id: str, type: str) -> list[str]:
    """Task ids associated with the report by the built-in signals pipeline (product `signals`) for
    the given `type`, oldest first.

    Thin wrapper over `SignalReport.associated_task_runs`, which unifies the `task_run` artefact log
    with the legacy `SignalReportTask` gate rows — so this is how a task's *purpose* is derived
    across both sources during the migration.
    """
    return [
        run.task_id
        for run in SignalReport.associated_task_runs(report_id=report_id, product=SIGNALS_PRODUCT, type=type)
    ]


def record_implementation_task(
    *, team_id: int, report_id: str, task_id: str, run_id: str | None = None, billing_exempt_reason: str | None = None
) -> SignalReportArtefact:
    """Record a started implementation task as BOTH the legacy `SignalReportTask` gate row and the
    `task_run` work-log artefact.

    `SignalReportTask` (an `implementation` row) is the auto-start idempotency gate — see
    `auto_start.py` — because the artefact log is freeform and API-mutable and so can't be trusted
    for a spend-controlling decision. We dual-write the artefact so that, once
    `backfill_task_run_artefacts` has converted every legacy row, the gate can switch to the
    artefact log and `SignalReportTask` can be dropped. Call inside the transaction that created
    the task. Shared by auto-start and the manual start-task API.

    `billing_exempt_reason` lets a caller that knows its origin is PostHog-system declare the
    report never-billable in the same transaction that records the task — before the run can ship
    a billable PR. Enforced by the prospective-only freeze rule (`billing.mark_report_billing_exempt`
    raises once a billable PR run exists). Auto-start stamps its exemption itself under its row
    lock and does not pass this.
    """
    if billing_exempt_reason:
        report = SignalReport.objects.select_for_update().get(id=report_id, team_id=team_id)
        mark_report_billing_exempt(report, billing_exempt_reason)
    SignalReportTask.objects.get_or_create(
        team_id=team_id,
        report_id=report_id,
        task_id=task_id,
        defaults={"relationship": TASK_RUN_TYPE_IMPLEMENTATION},
    )
    return append_task_run_artefact(
        team_id=team_id,
        report_id=report_id,
        product=SIGNALS_PRODUCT,
        type=TASK_RUN_TYPE_IMPLEMENTATION,
        task_id=task_id,
        run_id=run_id,
    )
