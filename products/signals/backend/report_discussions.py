"""The discussions people opened on the reports a scout wrote, read back by that scout.

`discussion_notes.py` pushes the opening question of an inbox "Discuss" task to the authoring scout
as a note, once, when the task is created. What the conversation concluded never reaches the scout
that way: the answer, any follow-up, and the outcome land later, as the `task_summary` each run of
the discussion task writes. This module is the pull side. A scout run lists the discussion tasks on
the reports it emitted or edited, each with its latest summary when that summary is safe to read.

Scope is set by provenance, never by the caller. The reports are the ones on the calling scout's own
`SignalScoutRun` rows (the inverse of `scout_authorship.resolve_touching_scout_skills`), and the view
resolves the scout from the run its sandbox token is bound to, so a scout cannot read another scout's
discussions. Only tasks on the canonical team qualify, as in `discussion_notes.py`, so a child
environment's discussion stays out of the parent project's scouts. Only tasks the whole team may
read qualify, and a summary the tasks facade keeps private comes back null.

A summary is free text that reaches a scout holding privileged tools, so it has to clear the same
bar as a scout note: the task's creator must pass `user_can_steer_scouts`. Every other row keeps its
report, status, and task id, with a null summary. Nothing records who wrote a summary: the discussion
agent writes it, but `set_summary` accepts any caller who controls the task, and any member controls
a null-channel discussion task, which is the usual inbox case. So a member who may not steer scouts
can write the summary on a discussion that a member who may steer scouts started. With default
access that member can leave a scout note anyway, and the scout reads a summary as evidence, never
as instructions. The question itself is never returned: the discussion note already carries it
behind the full steering gate, including the credential scopes this read cannot recover.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from django.db import models
from django.db.models import Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.signals.backend.artefact_schemas import SIGNALS_PRODUCT, TASK_RUN_TYPE_DISCUSSION
from products.signals.backend.dismissal_notes import user_can_steer_scouts
from products.signals.backend.models import SignalReport, SignalScoutRun
from products.tasks.backend.facade.api import TaskOriginProduct
from products.tasks.backend.facade.team_task_summaries import list_team_task_summaries

DEFAULT_DISCUSSIONS_SINCE = timedelta(days=14)
DEFAULT_DISCUSSIONS_LIMIT = 20
MAX_DISCUSSIONS_LIMIT = 50

# How far back the scout's own runs are read to find the reports it touched. A discussion opened
# today on a report filed months ago is still feedback on that report, so this is wider than the
# discussion window. The run cap bounds an hourly scout's history.
REPORT_LOOKBACK = timedelta(days=90)
MAX_RUNS_SCANNED = 1_000

_MAX_TITLE_CHARS = 200
_MAX_SUMMARY_CHARS = 4_000


class ReportInvolvement(models.TextChoices):
    AUTHORED = "authored"
    EDITED = "edited"


@frozen
class ReportDiscussion:
    report_id: str
    report_title: str
    involvement: ReportInvolvement
    task_id: str
    created_at: datetime
    active_at: datetime
    status: str | None
    task_summary: str | None


def list_report_discussions(
    *,
    team: Team,
    skill_name: str,
    report_id: str | None = None,
    since: datetime | None = None,
    limit: int = DEFAULT_DISCUSSIONS_LIMIT,
) -> list[ReportDiscussion]:
    """Discussion tasks on the reports `skill_name` emitted or edited, most recently active first.

    `since` keeps the discussions started or concluded at or after it, so an outcome written after
    a scout run still reaches the next run when the conversation began before it.

    `team` must be the canonical team the scout runs on. `report_id` narrows to one report, and
    returns nothing when the scout never touched it.
    """
    limit = max(0, min(limit, MAX_DISCUSSIONS_LIMIT))
    if limit == 0:
        return []
    active_after = since if since is not None else timezone.now() - DEFAULT_DISCUSSIONS_SINCE

    involvement = _touched_reports(team_id=team.id, skill_name=skill_name, report_id=report_id)
    if not involvement:
        return []
    reports = dict(
        SignalReport.objects.filter(team_id=team.id, id__in=list(involvement))
        .exclude(status=SignalReport.Status.DELETED)
        .values_list("id", "title")
    )
    report_titles = {str(report_id): title or "" for report_id, title in reports.items()}
    runs_by_report = SignalReport.associated_task_runs_for_reports(
        report_ids=list(report_titles), team_id=team.id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_DISCUSSION
    )
    report_by_task = {run.task_id: report_id for report_id, runs in runs_by_report.items() for run in runs}
    if not report_by_task:
        return []

    tasks = list_team_task_summaries(
        team_id=team.id,
        task_ids=list(report_by_task),
        origin_products=[TaskOriginProduct.SIGNAL_REPORT],
        active_after=active_after,
        limit=limit,
    )
    steering_creators = _creators_who_may_steer(team, (task.created_by_id for task in tasks if task.summary))

    discussions: list[ReportDiscussion] = []
    for task in tasks:
        discussion_report_id = report_by_task[task.task_id]
        summary = task.summary if task.created_by_id in steering_creators else None
        discussions.append(
            ReportDiscussion(
                report_id=discussion_report_id,
                report_title=report_titles[discussion_report_id][:_MAX_TITLE_CHARS],
                involvement=involvement[discussion_report_id],
                task_id=task.task_id,
                created_at=task.created_at,
                active_at=task.active_at,
                status=task.run_status,
                task_summary=summary[:_MAX_SUMMARY_CHARS] if summary else None,
            )
        )
    return discussions


def _touched_reports(*, team_id: int, skill_name: str, report_id: str | None) -> dict[str, ReportInvolvement]:
    """The reports this scout's recent runs emitted or edited. Authorship wins over an edit."""
    runs = SignalScoutRun.objects.for_team(team_id).filter(
        skill_name=skill_name, created_at__gte=timezone.now() - REPORT_LOOKBACK
    )
    if report_id is not None:
        runs = runs.filter(Q(emitted_report_ids__contains=[report_id]) | Q(edited_report_ids__contains=[report_id]))
    involvement: dict[str, ReportInvolvement] = {}
    for emitted_ids, edited_ids in runs.order_by("-created_at").values_list("emitted_report_ids", "edited_report_ids")[
        :MAX_RUNS_SCANNED
    ]:
        for emitted_id in emitted_ids or []:
            involvement[str(emitted_id)] = ReportInvolvement.AUTHORED
        for edited_id in edited_ids or []:
            involvement.setdefault(str(edited_id), ReportInvolvement.EDITED)
    if report_id is not None:
        return {report_id: involvement[report_id]} if report_id in involvement else {}
    return involvement


def _creators_who_may_steer(team: Team, creator_ids: Iterable[int | None]) -> set[int]:
    """The task creators who could have left a scout note by hand on this project."""
    ids = {creator_id for creator_id in creator_ids if creator_id is not None}
    if not ids:
        return set()
    return {user.id for user in User.objects.filter(id__in=ids) if user_can_steer_scouts(user, team)}
