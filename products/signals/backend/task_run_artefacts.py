"""Helpers for appending `task_run` log artefacts to a report.

A `task_run` artefact records that a `tasks.Task` ran for a report (research, implementation,
repo-selection, …) so the run shows up in the report's work-log timeline. The append lives here
as a single source of truth, shared by the live creation paths and the
`backfill_task_run_artefacts` management command.

Each artefact carries a `(product, type)` pair following the custom-agent identifier shape: the
built-in signals pipeline uses `product="signals"` with the `SignalReportTask.Relationship` value
as `type`; custom agents supply their own `identifier()` pair.
"""

from __future__ import annotations

from products.signals.backend.artefact_schemas import TaskRunArtefact
from products.signals.backend.models import SignalReportArtefact

# Product identifier for task runs driven by the built-in signals pipeline (research /
# implementation / repo-selection). Custom agents supply their own product via `identifier()`.
SIGNALS_PRODUCT = "signals"


def _task_run_content(product: str, type: str, task_id: str, run_id: str | None) -> str:
    return TaskRunArtefact(
        task_id=str(task_id),
        run_id=str(run_id) if run_id is not None else None,
        product=product,
        type=type,
    ).model_dump_json()


def append_task_run_artefact(
    *, team_id: int, report_id: str, product: str, type: str, task_id: str, run_id: str | None = None
) -> SignalReportArtefact:
    """Append a `task_run` log artefact recording that a task ran for the report (sync)."""
    return SignalReportArtefact.add_log(
        team_id=team_id,
        report_id=str(report_id),
        type=SignalReportArtefact.ArtefactType.TASK_RUN,
        content=_task_run_content(product, type, task_id, run_id),
    )


async def aappend_task_run_artefact(
    *, team_id: int, report_id: str, product: str, type: str, task_id: str, run_id: str | None = None
) -> SignalReportArtefact:
    """Append a `task_run` log artefact recording that a task ran for the report (async)."""
    return await SignalReportArtefact.objects.acreate(
        team_id=team_id,
        report_id=str(report_id),
        type=SignalReportArtefact.ArtefactType.TASK_RUN,
        content=_task_run_content(product, type, task_id, run_id),
    )
