"""Keep `SignalReport.has_implementation_pr` and `has_active_implementation_pr` equal to the link tables.

`implementation_pr_report_filter` is the source of truth. It reads five link sources, so the inbox
cannot afford to evaluate it for every report on each list and count. These helpers store its
answer on the report row instead. Receivers call `schedule_implementation_pr_cache_refresh` after a
link write, and the daily reconcile corrects rows that a write path outside the receivers left stale.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from django.db import transaction
from django.db.models import BooleanField, ExpressionWrapper, QuerySet
from django.db.models.signals import post_delete, post_save, pre_delete

import structlog

from posthog.dataclasses import frozen
from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team import Team

from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportAssignment,
    SignalReportPullRequest,
    SignalReportTask,
)
from products.signals.backend.report_actionability_repair import RepairedBatch, report_id_batches
from products.tasks.backend.facade.task_run_signals import connect_task_run_post_save

logger = structlog.get_logger(__name__)

_LINK_ARTEFACT_TYPES = frozenset(
    {SignalReportArtefact.ArtefactType.PULL_REQUEST, SignalReportArtefact.ArtefactType.TASK_RUN}
)
# A delete that starts at one of these removes the linked reports too, so their links need no refresh.
_REPORT_REMOVING_ORIGINS = (SignalReport, Team, Project, Organization)


@frozen
class LiveImplementationPrFlags:
    has_pr: ExpressionWrapper
    has_active_pr: ExpressionWrapper


def live_implementation_pr_flags(team_id: int, report_ids: Sequence[Any] | None = None) -> LiveImplementationPrFlags:
    """The source-of-truth filter as two per-report annotations: any PR, and an active PR."""
    from products.signals.backend.implementation_pr import (  # noqa: PLC0415 — keeps the tasks facade off the Django setup path, which imports this module for its receivers
        implementation_pr_report_filter,
    )

    return LiveImplementationPrFlags(
        has_pr=ExpressionWrapper(
            implementation_pr_report_filter(team_id=team_id, report_ids=report_ids), output_field=BooleanField()
        ),
        has_active_pr=ExpressionWrapper(
            implementation_pr_report_filter(team_id=team_id, active_only=True, report_ids=report_ids),
            output_field=BooleanField(),
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
        live = live_implementation_pr_flags(team_id, report_ids=locked)
        rows = (
            SignalReport.objects.filter(team_id=team_id, id__in=locked)
            .annotate(live_has_implementation_pr=live.has_pr, live_has_active_implementation_pr=live.has_active_pr)
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
            SignalReport.objects.filter(team_id=team_id, id__in=changed_ids).update(
                has_implementation_pr=has_pr, has_active_implementation_pr=has_active_pr
            )
        return sum(len(changed_ids) for changed_ids in changed.values())


def schedule_implementation_pr_cache_refresh(*, team_id: int, report_ids: Iterable[Any]) -> None:
    """Refresh after the current transaction commits, so the refresh reads the committed links."""
    ids = sorted({str(report_id) for report_id in report_ids if report_id is not None})
    if not ids:
        return

    def refresh_after_commit() -> None:
        try:
            refresh_implementation_pr_cache(team_id=team_id, report_ids=ids)
        except Exception:
            # The link write has committed, so its caller must not fail. The task retries the refresh.
            logger.warning(
                "signals.implementation_pr_cache.refresh_failed", team_id=team_id, report_count=len(ids), exc_info=True
            )
            from products.signals.backend.tasks import (  # noqa: PLC0415 — tasks imports this module
                refresh_report_implementation_pr_cache,
            )

            refresh_report_implementation_pr_cache.delay(team_id, ids)

    transaction.on_commit(refresh_after_commit, robust=True)


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


def _removes_the_report(origin: Any) -> bool:
    # Django passes the instance or queryset that `delete()` was called on as `origin`. A task
    # delete cascades into report links but leaves the reports, so only these origins skip the refresh.
    if origin is None:
        return False
    model = origin.model if isinstance(origin, QuerySet) else type(origin)
    return issubclass(model, _REPORT_REMOVING_ORIGINS)


def _refresh_for_report_link(sender: type, instance: Any, **kwargs: Any) -> None:
    if _removes_the_report(kwargs.get("origin")):
        return
    schedule_implementation_pr_cache_refresh(team_id=instance.team_id, report_ids=[instance.report_id])


def _refresh_for_artefact(sender: type, instance: SignalReportArtefact, **kwargs: Any) -> None:
    if instance.type not in _LINK_ARTEFACT_TYPES or _removes_the_report(kwargs.get("origin")):
        return
    schedule_implementation_pr_cache_refresh(team_id=instance.team_id, report_ids=[instance.report_id])


def _refresh_for_pull_request(sender: type, instance: SignalReportPullRequest, **kwargs: Any) -> None:
    if _removes_the_report(kwargs.get("origin")):
        return
    report_ids = SignalReportArtefact.objects.filter(
        team_id=instance.team_id, type=SignalReportArtefact.ArtefactType.PULL_REQUEST, pull_request_id=instance.id
    ).values_list("report_id", flat=True)
    schedule_implementation_pr_cache_refresh(team_id=instance.team_id, report_ids=list(report_ids))


def _refresh_for_task_run(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    # TaskRun is a hot model, so the in-memory checks run before the first query. The filter reads
    # the run's output and its `state.ai_stage`. An output write can also remove a PR, so it always
    # refreshes; a full save is checked only when the run carries a PR, and the reconcile covers the rest.
    output = instance.output if isinstance(instance.output, dict) else {}
    carries_pr = bool(output.get("pr_url") or output.get("pr_urls"))
    update_fields = kwargs.get("update_fields")
    if created or update_fields is None:
        if not carries_pr:
            return
    elif "output" not in update_fields and not ("state" in update_fields and carries_pr):
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
    for batch in report_id_batches(team_id=team_id, batch_size=batch_size, after=after):
        by_team: dict[int, list[Any]] = defaultdict(list)
        for report_id, row_team_id in batch.rows:
            by_team[row_team_id].append(report_id)
        corrected = sum(
            refresh_implementation_pr_cache(team_id=row_team_id, report_ids=ids) for row_team_id, ids in by_team.items()
        )
        yield RepairedBatch(scanned=len(batch.rows), corrected=corrected, cursor=batch.cursor)
