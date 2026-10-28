"""Keep `SignalReport.has_implementation_pr` and `has_active_implementation_pr` equal to the link tables.

`implementation_pr_report_filter` is the source of truth. It reads five link sources, so the inbox
cannot afford to evaluate it for every report on each list and count. These helpers store its
answer on the report row instead. Receivers call `schedule_implementation_pr_cache_refresh` after a
link write, and the repair loop corrects rows that a write path outside the receivers left stale.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator
from functools import partial
from typing import Any

from django.db import transaction
from django.db.models import BooleanField, ExpressionWrapper, QuerySet
from django.db.models.signals import post_delete, post_save, pre_delete

from products.signals.backend.implementation_pr import implementation_pr_report_filter
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportPullRequest,
    SignalReportTask,
)
from products.signals.backend.report_actionability_repair import RepairedBatch
from products.tasks.backend.facade.task_run_signals import connect_task_run_post_save

_LINK_ARTEFACT_TYPES = frozenset(
    {SignalReportArtefact.ArtefactType.PULL_REQUEST, SignalReportArtefact.ArtefactType.TASK_RUN}
)


def live_implementation_pr_flags(team_id: int) -> tuple[ExpressionWrapper, ExpressionWrapper]:
    """The source-of-truth filter as two per-report annotations: any PR, and an active PR."""
    return (
        ExpressionWrapper(implementation_pr_report_filter(team_id=team_id), output_field=BooleanField()),
        ExpressionWrapper(
            implementation_pr_report_filter(team_id=team_id, active_only=True), output_field=BooleanField()
        ),
    )


def refresh_implementation_pr_cache(*, team_id: int, report_ids: Iterable[Any]) -> int:
    """Recompute the cached flags of these reports and store the ones that changed.

    Returns how many reports changed. The rows stay locked from the read to the write, so a refresh
    that read the links before a concurrent link write committed cannot overwrite the newer answer.
    """
    ids = sorted({str(report_id) for report_id in report_ids})
    if not ids:
        return 0
    with transaction.atomic():
        # FOR NO KEY UPDATE, for the reason `refresh_latest_actionability` gives: link inserts hold
        # KEY SHARE on the report through their foreign key.
        locked = list(
            SignalReport.objects.select_for_update(no_key=True)
            .filter(team_id=team_id, id__in=ids)
            .order_by("id")
            .values_list("id", flat=True)
        )
        if not locked:
            return 0
        live_has, live_active = live_implementation_pr_flags(team_id)
        rows = (
            SignalReport.objects.filter(id__in=locked)
            .annotate(live_has_implementation_pr=live_has, live_has_active_implementation_pr=live_active)
            .values_list(
                "id",
                "has_implementation_pr",
                "has_active_implementation_pr",
                "live_has_implementation_pr",
                "live_has_active_implementation_pr",
            )
        )
        changed: dict[tuple[bool, bool], list[Any]] = defaultdict(list)
        for report_id, cached_has, cached_active, has_pr, has_active_pr in rows:
            if (cached_has, cached_active) != (has_pr, has_active_pr):
                changed[(has_pr, has_active_pr)].append(report_id)
        for (has_pr, has_active_pr), changed_ids in changed.items():
            # `update()`, not `save()`: a cache refresh must not bump `updated_at`, which the inbox
            # sorts on, or fire the report's save receivers.
            SignalReport.objects.filter(id__in=changed_ids).update(
                has_implementation_pr=has_pr, has_active_implementation_pr=has_active_pr
            )
        return sum(len(changed_ids) for changed_ids in changed.values())


def schedule_implementation_pr_cache_refresh(*, team_id: int, report_ids: Iterable[Any]) -> None:
    """Refresh after the current transaction commits, so the refresh reads the committed links."""
    ids = [report_id for report_id in report_ids if report_id is not None]
    if ids:
        transaction.on_commit(partial(refresh_implementation_pr_cache, team_id=team_id, report_ids=ids), robust=True)


def connect_implementation_pr_cache_receivers() -> None:
    # Save only on SignalReportAssignment: it is a read-only legacy table, and a delete receiver would
    # stop report deletes from fast-deleting its rows.
    post_save.connect(_refresh_for_report_link, sender=SignalReportAssignment, dispatch_uid="pr_cache_save_assignment")
    post_save.connect(_refresh_for_report_link, sender=SignalReportTask, dispatch_uid="pr_cache_save_report_task")
    post_delete.connect(_refresh_for_report_link, sender=SignalReportTask, dispatch_uid="pr_cache_delete_report_task")
    post_save.connect(_refresh_for_artefact, sender=SignalReportArtefact, dispatch_uid="pr_cache_save_artefact")
    post_delete.connect(_refresh_for_artefact, sender=SignalReportArtefact, dispatch_uid="pr_cache_delete_artefact")
    post_save.connect(_refresh_for_pull_request, sender=SignalReportPullRequest, dispatch_uid="pr_cache_save_pr")
    # Before the delete: the artefacts' SET_NULL clears the link this receiver reads.
    pre_delete.connect(_refresh_for_pull_request, sender=SignalReportPullRequest, dispatch_uid="pr_cache_delete_pr")
    connect_task_run_post_save(_refresh_for_task_run, dispatch_uid="signals_pr_cache_task_run")


def _cascaded(origin: Any, sender: type) -> bool:
    # A delete that cascades from a report or a team leaves no report to refresh, so it skips the
    # query. Django passes the instance or queryset that `delete()` was called on as `origin`.
    if origin is None:
        return False
    model = origin.model if isinstance(origin, QuerySet) else type(origin)
    return model is not sender


def _refresh_for_report_link(sender: type, instance: Any, **kwargs: Any) -> None:
    if _cascaded(kwargs.get("origin"), sender):
        return
    schedule_implementation_pr_cache_refresh(team_id=instance.team_id, report_ids=[instance.report_id])


def _refresh_for_artefact(sender: type, instance: SignalReportArtefact, **kwargs: Any) -> None:
    if instance.type not in _LINK_ARTEFACT_TYPES or _cascaded(kwargs.get("origin"), sender):
        return
    schedule_implementation_pr_cache_refresh(team_id=instance.team_id, report_ids=[instance.report_id])


def _refresh_for_pull_request(sender: type, instance: SignalReportPullRequest, **kwargs: Any) -> None:
    if _cascaded(kwargs.get("origin"), sender):
        return
    report_ids = SignalReportArtefact.objects.filter(
        team_id=instance.team_id, type=SignalReportArtefact.ArtefactType.PULL_REQUEST, pull_request_id=instance.id
    ).values_list("report_id", flat=True)
    schedule_implementation_pr_cache_refresh(team_id=instance.team_id, report_ids=list(report_ids))


def _refresh_for_task_run(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    # TaskRun is a hot model, so the in-memory checks run before the first query. Only a run whose
    # output carries a PR can make the filter's task branches match.
    if created:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not {"output", "state", "status"}.intersection(update_fields):
        return
    output = instance.output if isinstance(instance.output, dict) else {}
    if not output.get("pr_url") and not output.get("pr_urls"):
        return
    team_id, task_id = instance.team_id, instance.task_id
    report_ids = {
        *SignalReportArtefact.objects.filter(
            team_id=team_id, type=SignalReportArtefact.ArtefactType.TASK_RUN, task_id=task_id
        ).values_list("report_id", flat=True),
        *SignalReportTask.objects.filter(team_id=team_id, task_id=task_id).values_list("report_id", flat=True),
        *SignalReportAssignment.all_teams.filter(team_id=team_id, actor_task_id=task_id).values_list(
            "report_id", flat=True
        ),
    }
    schedule_implementation_pr_cache_refresh(team_id=team_id, report_ids=report_ids)


def repair_implementation_pr_cache(
    *, team_id: int | None, batch_size: int, after: str | None = None
) -> Iterator[RepairedBatch]:
    """Recompute the cached flags of every report, one batch at a time, starting after report id `after`."""
    reports = SignalReport.objects.all()
    if team_id is not None:
        reports = reports.filter(team_id=team_id)
    reports = reports.order_by("id")
    while True:
        page = reports.filter(id__gt=after) if after else reports
        rows = list(page.values_list("id", "team_id")[:batch_size])
        if not rows:
            return
        after = str(rows[-1][0])
        by_team: dict[int, list[Any]] = defaultdict(list)
        for report_id, row_team_id in rows:
            by_team[row_team_id].append(report_id)
        corrected = sum(
            refresh_implementation_pr_cache(team_id=row_team_id, report_ids=ids) for row_team_id, ids in by_team.items()
        )
        yield RepairedBatch(scanned=len(rows), corrected=corrected, cursor=after)
