import re
import json
from dataclasses import replace
from datetime import datetime
from typing import Any

from django.utils import timezone

from posthog.dataclasses import frozen

from ..models import SignalReport, SignalReportArtefact, SignalScoutGoal, SignalScoutGoalIdea, SignalScoutRun
from ..scout_authorship import GOAL_RUN_METADATA_KEY

TRACKING_TAG = "goal-tracking"
IDEA_TAG = "goal-idea"
SUPPORTED_TAG = "supported"
NOT_SUPPORTED_TAG = "not-supported"
OWNER_TAG = re.compile(r"^owner-idea-(\d+)$")
OWNER_TITLE = re.compile(r"^\s*(?:goal idea:\s*)?owner idea (\d+)\s*[:.\-]\s*", re.IGNORECASE)
IDEA_PREFIX = re.compile(r"^\s*goal idea:\s*", re.IGNORECASE)
VERDICT = re.compile(r"^\W*(not supported|supported)\b", re.IGNORECASE)
AUDIENCE = re.compile(r"^\W*audience\W*:\D*([\d,]+)", re.IGNORECASE | re.MULTILINE)
METRIC = re.compile(r"^\W*metric\W*:\s*(.+?)\W*$", re.IGNORECASE | re.MULTILINE)
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
MAX_EVIDENCE = 8
EVIDENCE_KINDS = (
    ("/replay/", "replay"),
    ("session_recording", "replay"),
    ("/insights/", "insight"),
    ("/experiments/", "experiment"),
    ("/error_tracking/", "error"),
)
PROPOSED_STATUSES = (SignalReport.Status.READY, SignalReport.Status.PENDING_INPUT)

SCOUT = "scout"
OWNER = "owner"
PROPOSED = "proposed"
DISMISSED = "dismissed"
PENDING = "pending"
SUPPORTED = "supported"
NOT_SUPPORTED = "not_supported"


@frozen
class IdeaView:
    id: str
    kind: str
    stage: str
    source: str
    owner_number: int | None
    assessment: str
    title: str
    summary: str
    report_id: str | None
    evidence: list[dict[str, str]]
    moves_metric: str
    audience: int | None
    dismissed_reason: str
    created_at: datetime
    row: SignalScoutGoalIdea | None


def evidence_from(summary: str) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for label, url in LINK.findall(summary):
        kind = (
            "chart"
            if url.startswith("chart:")
            else next((kind for marker, kind in EVIDENCE_KINDS if marker in url), "link")
        )
        found.setdefault(url, {"kind": kind, "label": label.strip()[:200], "url": url})
    return list(found.values())[:MAX_EVIDENCE]


def owner_number(report: SignalReport) -> int | None:
    for tag in report.tags or []:
        if match := OWNER_TAG.match(tag):
            return int(match.group(1))
    match = OWNER_TITLE.match(report.title or "")
    return int(match.group(1)) if match else None


def assessment(report: SignalReport, *, default: str) -> str:
    tags = set(report.tags or [])
    if NOT_SUPPORTED_TAG in tags:
        return NOT_SUPPORTED
    if SUPPORTED_TAG in tags:
        return SUPPORTED
    match = VERDICT.match((report.summary or "").strip())
    if match:
        return NOT_SUPPORTED if match.group(1).lower() == "not supported" else SUPPORTED
    return default


def clean_title(title: str) -> str:
    title = OWNER_TITLE.sub("", IDEA_PREFIX.sub("", title)).strip()
    return title[:1].upper() + title[1:]


def goal_reports(goal: SignalScoutGoal, extra_ids: list[str]) -> list[SignalReport]:
    emitted = (
        SignalScoutRun.objects.for_team(goal.team_id)
        .filter(scout_config_id=goal.pk, **{f"metadata__{GOAL_RUN_METADATA_KEY}": str(goal.pk)})
        .exclude(emitted_report_ids=[])
        .exclude(emitted_report_ids__isnull=True)
        .values_list("emitted_report_ids", flat=True)
    )
    ids = {str(report_id) for batch in emitted for report_id in batch or []} | set(extra_ids)
    if not ids:
        return []
    return list(
        SignalReport.objects.filter(team_id=goal.team_id, id__in=ids)
        .exclude(status=SignalReport.Status.DELETED)
        .order_by("created_at")
    )


def dismissal_notes(team_id: int, report_ids: list[str]) -> dict[str, str]:
    notes: dict[str, str] = {}
    if not report_ids:
        return notes
    for report_id, content in (
        SignalReportArtefact.objects.filter(
            team_id=team_id, report_id__in=report_ids, type=SignalReportArtefact.ArtefactType.DISMISSAL
        )
        .order_by("created_at")
        .values_list("report_id", "content")
    ):
        try:
            data: Any = json.loads(content)
        except (TypeError, ValueError):
            data = {}
        notes[str(report_id)] = str((data or {}).get("note") or (data or {}).get("reason") or "Dismissed.")
    return notes


def _audience(summary: str) -> int | None:
    match = AUDIENCE.search(summary)
    return int(match.group(1).replace(",", "")) if match else None


def _moves_metric(summary: str) -> str:
    match = METRIC.search(summary)
    return match.group(1).strip("* ")[:255] if match else ""


def _owner_titles(goal: SignalScoutGoal) -> dict[int, str]:
    return {int(item["number"]): str(item["title"]) for item in goal.owner_ideas or []}


def _view(
    *,
    view_id: str,
    report: SignalReport | None,
    stage: str,
    owner: int | None,
    owner_titles: dict[int, str],
    row: SignalScoutGoalIdea | None = None,
    dismissed_reason: str = "",
    default_assessment: str = SUPPORTED,
) -> IdeaView:
    summary = (report.summary or "") if report else ""
    title = owner_titles.get(owner, "") if owner is not None else ""
    return IdeaView(
        id=view_id,
        kind=row.kind if row else SignalScoutGoalIdea.Kind.IDEA,
        stage=stage,
        source=OWNER if owner is not None else SCOUT,
        owner_number=owner,
        assessment=assessment(report, default=PENDING if owner is not None else default_assessment)
        if report
        else PENDING,
        title=(title or clean_title(report.title or "") if report else title)[:255] or "Idea",
        summary=summary,
        report_id=str(report.id) if report else None,
        evidence=evidence_from(summary),
        moves_metric=_moves_metric(summary),
        audience=_audience(summary),
        dismissed_reason=dismissed_reason,
        created_at=row.created_at if row else report.created_at if report else timezone.now(),
        row=row,
    )


def goal_ideas(goal: SignalScoutGoal) -> list[IdeaView]:
    rows = list(SignalScoutGoalIdea.objects.for_team(goal.team_id).filter(goal=goal).order_by("created_at"))
    row_by_report = {str(row.report_id): row for row in rows}
    reports = goal_reports(goal, list(row_by_report))
    by_id = {str(report.id): report for report in reports}
    owner_titles = _owner_titles(goal)
    suppressed = [str(report.id) for report in reports if report.status == SignalReport.Status.SUPPRESSED]
    notes = dismissal_notes(goal.team_id, suppressed)
    views: list[IdeaView] = []
    for row in rows:
        report = by_id.get(str(row.report_id))
        number = owner_number(report) if report and row.kind == SignalScoutGoalIdea.Kind.IDEA else None
        view = _view(
            view_id=str(row.id), report=report, stage=row.stage, owner=number, owner_titles=owner_titles, row=row
        )
        if row.kind == SignalScoutGoalIdea.Kind.TRACKING:
            view = replace(view, title=(report.title if report else "") or "Check how the goal is measured")
        views.append(view)
    latest_owner: dict[int, SignalReport] = {}
    scout_reports: list[SignalReport] = []
    for report in reports:
        if str(report.id) in row_by_report or TRACKING_TAG in (report.tags or []):
            continue
        number = owner_number(report)
        if number is None:
            scout_reports.append(report)
        else:
            latest_owner[number] = report
    built_owner_numbers = {view.owner_number for view in views if view.owner_number is not None}
    for report in scout_reports:
        report_id = str(report.id)
        if report.status in PROPOSED_STATUSES:
            views.append(_view(view_id=report_id, report=report, stage=PROPOSED, owner=None, owner_titles=owner_titles))
        elif report.status == SignalReport.Status.SUPPRESSED and report_id in notes:
            views.append(
                _view(
                    view_id=report_id,
                    report=report,
                    stage=DISMISSED,
                    owner=None,
                    owner_titles=owner_titles,
                    dismissed_reason=notes[report_id],
                )
            )
    for number in owner_titles:
        if number in built_owner_numbers:
            continue
        found = latest_owner.get(number)
        if found is None:
            views.append(
                _view(view_id=f"owner-{number}", report=None, stage=PROPOSED, owner=number, owner_titles=owner_titles)
            )
            continue
        report_id = str(found.id)
        if found.status == SignalReport.Status.SUPPRESSED:
            dismissed = report_id in notes
            views.append(
                _view(
                    view_id=report_id,
                    report=found,
                    stage=DISMISSED if dismissed else PROPOSED,
                    owner=number,
                    owner_titles=owner_titles,
                    dismissed_reason=notes.get(report_id, ""),
                    default_assessment=NOT_SUPPORTED,
                )
            )
            if not dismissed:
                views[-1] = replace(views[-1], assessment=NOT_SUPPORTED)
        elif found.status in PROPOSED_STATUSES:
            views.append(
                _view(view_id=report_id, report=found, stage=PROPOSED, owner=number, owner_titles=owner_titles)
            )
    return sorted(views, key=lambda view: view.created_at, reverse=True)


def open_row(views: list[IdeaView], kind: str = SignalScoutGoalIdea.Kind.IDEA) -> IdeaView | None:
    return next(
        (view for view in views if view.row and view.kind == kind and view.stage in SignalScoutGoalIdea.OPEN_STAGES),
        None,
    )


def tracking_view(views: list[IdeaView]) -> IdeaView | None:
    return next((view for view in views if view.kind == SignalScoutGoalIdea.Kind.TRACKING), None)


def unchecked_owner_ideas(views: list[IdeaView]) -> list[IdeaView]:
    return [view for view in views if view.source == OWNER and view.stage == PROPOSED and view.report_id is None]


def ready_ideas(views: list[IdeaView]) -> list[IdeaView]:
    return [
        view
        for view in views
        if view.kind == SignalScoutGoalIdea.Kind.IDEA and view.stage == PROPOSED and view.report_id is not None
    ]
