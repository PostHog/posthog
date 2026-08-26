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

from django.db import transaction

from products.signals.backend.artefact_schemas import (
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_DISCUSSION,
    TASK_RUN_TYPE_IMPLEMENTATION,
    TASK_RUN_TYPE_REPO_SELECTION,
    TASK_RUN_TYPE_RESEARCH,
    TASK_RUN_TYPE_SCOUT,
    NoteArtefact,
    TaskRunArtefact,
)
from products.signals.backend.billing import first_billable_pr_run_at, mark_report_billing_exempt
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact, SignalReportTask

# The task-run vocabulary lives in `artefact_schemas` (a leaf module the model layer can import
# without a cycle); re-exported here so existing `from task_run_artefacts import …` callers keep
# working.
__all__ = [
    "MAX_DISCUSSION_TASKS_PER_REPORT",
    "SIGNALS_PRODUCT",
    "TASK_RUN_TYPE_DISCUSSION",
    "TASK_RUN_TYPE_IMPLEMENTATION",
    "TASK_RUN_TYPE_REPO_SELECTION",
    "TASK_RUN_TYPE_RESEARCH",
    "ReportTaskCapExceeded",
    "aappend_task_run_artefact",
    "append_task_run_artefact",
    "enforce_report_implementation_rerun_cap",
    "enforce_report_task_cap",
    "record_implementation_task",
    "record_report_task",
    "release_quota_cancelled_implementation",
    "signals_task_ids",
]

# One report funds at most this many user-started discussion tasks, on top of one live
# implementation. Inference on these tasks is unbilled (per-PR pricing), so without a cap a
# single report is an unlimited font of free agent runs; the number only needs to cover honest
# "ask a follow-up in a fresh task" use, since conversation *within* a task is unlimited.
MAX_DISCUSSION_TASKS_PER_REPORT = 3

# `scout` excluded too: it labels the scout run that authored the report, is server-written, and
# is rejected as a client-asserted relationship by the tasks write serializer.
_PIPELINE_TASK_RUN_TYPES = frozenset(
    {TASK_RUN_TYPE_IMPLEMENTATION, TASK_RUN_TYPE_RESEARCH, TASK_RUN_TYPE_REPO_SELECTION, TASK_RUN_TYPE_SCOUT}
)

# Pipeline runs that never open a PR for the report. Research and repo-selection runs sit on the
# base branch and read other people's PRs while checking for in-flight work, so a PR URL on one of
# their runs is something the agent looked at, not something it shipped. Kept as a denylist so a
# new run type that does ship code (a report is expected to grow several PRs) counts by default.
NON_PR_BEARING_TASK_RUN_TYPES = frozenset({TASK_RUN_TYPE_RESEARCH, TASK_RUN_TYPE_REPO_SELECTION, TASK_RUN_TYPE_SCOUT})

_TERMINAL_NO_PR_RUN_STATUSES = frozenset({"failed", "cancelled"})

_GITHUB_PR_URL_PREFIX = "https://github.com/"


class ReportTaskCapExceeded(Exception):
    """A signal report already has its allowance of user-started tasks."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


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


def _live_implementation_exists(*, team_id: int, report_id: str, exclude_task_id: str | None = None) -> bool:
    """Whether the report has an implementation task that still claims its one slot.

    Reads the `SignalReportTask` gate rows (not the API-mutable artefact log) and traverses
    to runs via the FK, staying behind the tasks public interface like `billing`. A task
    releases the slot only when it is deleted or every one of its runs ended failed/cancelled
    without shipping a GitHub PR — a task with no runs yet still claims it, and a shipped PR
    claims it permanently (the report is implemented). Quota-cancelled implementations delete
    their gate rows (`release_quota_cancelled_implementation`), so they never count.
    """
    claimants = SignalReportTask.objects.filter(
        team_id=team_id, report_id=report_id, relationship=TASK_RUN_TYPE_IMPLEMENTATION
    ).exclude(task__deleted=True)
    if exclude_task_id is not None:
        claimants = claimants.exclude(task_id=exclude_task_id)
    rows = claimants.values_list("task_id", "task__runs__status", "task__runs__output__pr_url")
    runs_by_task: dict[str, list[tuple[str | None, object]]] = {}
    for task_id, status, pr_url in rows:
        runs_by_task.setdefault(str(task_id), []).append((status, pr_url))
    for runs in runs_by_task.values():
        has_runs = any(run_status is not None for run_status, _run_pr_url in runs)
        if not has_runs:
            return True
        for run_status, run_pr_url in runs:
            if run_status is None:
                continue
            if run_status not in _TERMINAL_NO_PR_RUN_STATUSES:
                return True
            if isinstance(run_pr_url, str) and run_pr_url.startswith(_GITHUB_PR_URL_PREFIX):
                return True
    return False


def enforce_report_task_cap(*, team_id: int, report_id: str, relationship: str | None) -> None:
    """Cap the tasks a single report can spawn; raises `ReportTaskCapExceeded` at the limit.

    Inference on report-started tasks is unbilled (the customer pays per PR), so the report is
    the resource being spent and the cap belongs on it: one live implementation, and at most
    `MAX_DISCUSSION_TASKS_PER_REPORT` tasks with any other relationship. This is defense in depth
    over the gateway's `signals_interactive` per-user budget and per-task spend ceiling.

    Must be called inside an open transaction: it locks the report row — the same lock
    auto-start's `_create_implementation_task_if_absent` takes — so concurrent creates
    serialize instead of both passing the count check.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("enforce_report_task_cap must run inside a transaction; it locks the report row")
    report = SignalReport.objects.select_for_update().filter(id=report_id, team_id=team_id).first()
    if report is None:
        # The serializer already team-scoped the report; behave as the create path would without a cap.
        return
    if relationship is None or relationship == TASK_RUN_TYPE_IMPLEMENTATION:
        if _live_implementation_exists(team_id=team_id, report_id=report_id):
            raise ReportTaskCapExceeded(
                kind=TASK_RUN_TYPE_IMPLEMENTATION,
                detail="A PR task already exists for this report. Open the existing task to continue.",
            )
        return
    # Any non-implementation label is a discussion for cap purposes; server-only pipeline labels
    # can't reach here (the write serializer rejects them) and are excluded from the count.
    # Counting is status-independent: a discussion that ended still consumed inference.
    discussions = [
        run
        for run in SignalReport.associated_task_runs(report_id=report_id, team_id=team_id, product=SIGNALS_PRODUCT)
        if run.type not in _PIPELINE_TASK_RUN_TYPES
    ]
    if len(discussions) >= MAX_DISCUSSION_TASKS_PER_REPORT:
        raise ReportTaskCapExceeded(
            kind=TASK_RUN_TYPE_DISCUSSION,
            detail="This report has reached its limit of AI discussions. Open an existing discussion task to continue.",
        )


def enforce_report_implementation_rerun_cap(*, team_id: int, report_id: str, task_id: str) -> None:
    """Re-check the one-live-implementation slot before starting another run of an existing task.

    `enforce_report_task_cap` guards task *creation*, but a task outlives its runs. An
    implementation whose every run ended failed/cancelled without a PR releases its slot, which
    lets a second implementation be created for the report — and then running the first one again
    would put two live implementations on it, spending unbilled inference twice over.

    Only another task holding the slot blocks: a task reclaiming the slot it released is the
    ordinary "my run failed, try again" path and stays allowed. Non-implementation tasks are
    unaffected, since the discussion cap counts tasks rather than runs and conversation inside
    one is deliberately unlimited.

    Must be called inside an open transaction: it locks the report row, the same lock creation
    and auto-start take. That lock only serializes for as long as the caller's transaction stays
    open, and a live run is what marks the slot taken, so a caller that goes on to start the run
    has to insert the run row in this same transaction. Releasing the lock first would leave the
    task looking released for the whole span before the insert, which is long enough for a
    concurrent create to pass its own count check.
    """
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError(
            "enforce_report_implementation_rerun_cap must run inside a transaction; it locks the report row"
        )
    is_implementation = SignalReportTask.objects.filter(
        team_id=team_id, report_id=report_id, task_id=task_id, relationship=TASK_RUN_TYPE_IMPLEMENTATION
    ).exists()
    if not is_implementation:
        return
    report = SignalReport.objects.select_for_update().filter(id=report_id, team_id=team_id).first()
    if report is None:
        return
    if _live_implementation_exists(team_id=team_id, report_id=report_id, exclude_task_id=task_id):
        raise ReportTaskCapExceeded(
            kind=TASK_RUN_TYPE_IMPLEMENTATION,
            detail="A PR task already exists for this report. Open the existing task to continue.",
        )


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


def record_report_task(
    *, team_id: int, report_id: str, task_id: str, relationship: str | None = None, run_id: str | None = None
) -> SignalReportArtefact:
    """Record a task↔report association a client asserted when creating a task from the report.

    `implementation` (also the default when no relationship is given) additionally writes the legacy
    `SignalReportTask` gate row that guards auto-start spend, via `record_implementation_task`. Every
    other relationship records only the `task_run` work-log artefact under `product="signals"`
    (`research` never reaches here — it is created solely by the server-side research pipeline).
    """
    if relationship is None or relationship == TASK_RUN_TYPE_IMPLEMENTATION:
        return record_implementation_task(team_id=team_id, report_id=report_id, task_id=task_id, run_id=run_id)
    return append_task_run_artefact(
        team_id=team_id,
        report_id=report_id,
        product=SIGNALS_PRODUCT,
        type=relationship,
        task_id=task_id,
        run_id=run_id,
    )


def release_quota_cancelled_implementation(*, team_id: int, task_id: str) -> list[str]:
    """Remove a quota-cancelled implementation's auto-start records so its report can be
    implemented again by a later cycle.

    A run the quota gate cancels mid-flight never shipped its PR, but its `SignalReportTask` gate
    row and implementation `task_run` artefact would keep `associated_task_runs` reporting a
    started implementation and permanently block re-implementation. Deleting both restores the
    report to "never implemented"; a system `note` artefact records for the report timeline why
    the run stopped. Locks each report row (the same lock auto-start creation takes) so the
    removal serializes with a concurrent auto-start evaluation. Returns the affected report ids
    (empty when the task has no implementation link).

    Reports that already shipped a billable PR are skipped entirely: the cancel decision is
    run-scoped but this delete is task-scoped, and a sibling run of the same task may have
    shipped the PR that billed the report. Its `SignalReportTask` row is billing's evidence —
    the `billed_earlier` dedup and refund eligibility both resolve through it — so deleting it
    would re-bill the report on its next implementation and strand the paid charge unrefundable.
    """
    report_ids = list(
        SignalReportTask.objects.filter(
            team_id=team_id, task_id=task_id, relationship=TASK_RUN_TYPE_IMPLEMENTATION
        ).values_list("report_id", flat=True)
    )
    released: list[str] = []
    for report_id in report_ids:
        with transaction.atomic():
            report = SignalReport.objects.select_for_update().filter(id=report_id, team_id=team_id).first()
            if report is None:
                continue
            if first_billable_pr_run_at(report_id) is not None:
                # A sibling run already shipped this report's billable PR. These records are
                # billing's evidence for that charge — deleting them would double-bill the next
                # implementation — and the report needs no release: it *is* implemented.
                continue
            SignalReportTask.objects.filter(
                team_id=team_id,
                report_id=report_id,
                task_id=task_id,
                relationship=TASK_RUN_TYPE_IMPLEMENTATION,
            ).delete()
            for artefact in SignalReportArtefact.objects.filter(
                team_id=team_id,
                report_id=report_id,
                task_id=task_id,
                type=SignalReportArtefact.ArtefactType.TASK_RUN,
            ):
                try:
                    content = json.loads(artefact.content)
                except (TypeError, ValueError):
                    continue
                if content.get("product") == SIGNALS_PRODUCT and content.get("type") == TASK_RUN_TYPE_IMPLEMENTATION:
                    artefact.delete()
            SignalReportArtefact.add_log(
                team_id=team_id,
                report_id=str(report_id),
                content=NoteArtefact(
                    note=(
                        "Implementation run stopped: the organization reached its self-driving pull request "
                        "limit. A new run can start after the limit is raised or the billing period resets."
                    )
                ),
                attribution=ArtefactAttribution.system(),
            )
            released.append(str(report_id))
    return released
