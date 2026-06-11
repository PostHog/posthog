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

import json

from posthog.sync import database_sync_to_async

from products.signals.backend.artefact_schemas import TaskRunArtefact, validate_artefact_content
from products.signals.backend.models import ArtefactAttribution, SignalReportArtefact

# Product identifier for task runs driven by the built-in signals pipeline (research /
# implementation / repo-selection). Custom agents supply their own product via `identifier()`.
SIGNALS_PRODUCT = "signals"

# `type` values used by the built-in pipeline's task runs.
TASK_RUN_TYPE_REPO_SELECTION = "repo_selection"
TASK_RUN_TYPE_RESEARCH = "research"
TASK_RUN_TYPE_IMPLEMENTATION = "implementation"


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
    """Append a `task_run` log artefact recording that a task ran for the report (sync).

    Always attributed to the task it records — that task *is* the producer of the entry.
    """
    return SignalReportArtefact.add_log(
        team_id=team_id,
        report_id=str(report_id),
        type=SignalReportArtefact.ArtefactType.TASK_RUN,
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
        content=validate_artefact_content(
            SignalReportArtefact.ArtefactType.TASK_RUN, _task_run_content(product, type, task_id, run_id)
        ),
        task_id=str(task_id),
    )


def signals_task_ids(*, report_id: str, type: str) -> list[str]:
    """Task ids recorded by the built-in signals pipeline's `task_run` artefacts of `type` for
    the report, oldest first.

    This is how a task's *purpose* is derived now that task↔report associations are unlabelled.
    Rows are parse-confirmed in Python rather than via a `content::jsonb` cast: a report has only
    a handful of task_run rows, and a cast would raise on any malformed legacy TextField content.
    """
    task_ids: list[str] = []
    for content in (
        SignalReportArtefact.objects.filter(report_id=report_id, type=SignalReportArtefact.ArtefactType.TASK_RUN)
        .order_by("created_at")
        .values_list("content", flat=True)
    ):
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            continue
        if (
            isinstance(parsed, dict)
            and parsed.get("product") == SIGNALS_PRODUCT
            and parsed.get("type") == type
            and parsed.get("task_id")
        ):
            task_ids.append(str(parsed["task_id"]))
    return task_ids


def has_signals_task_run(*, report_id: str, type: str) -> bool:
    """True when a `task_run` artefact from the built-in signals pipeline with the given `type`
    exists for the report — e.g. the auto-start "has an implementation started?" idempotency check.
    """
    return bool(signals_task_ids(report_id=report_id, type=type))


async def ahas_signals_task_run(*, report_id: str, type: str) -> bool:
    """Async wrapper for `has_signals_task_run`."""
    return await database_sync_to_async(has_signals_task_run, thread_sensitive=False)(report_id=report_id, type=type)
