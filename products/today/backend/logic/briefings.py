"""Reading and starting briefings for the API and the MCP tools."""

import asyncio
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

import structlog
from temporalio.common import WorkflowIDReusePolicy

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.temporal.common.client import sync_connect

from products.signals.backend.facade import api as signals

from ..facade import contracts
from ..facade.enums import BriefingStatus, BriefingTrigger, BriefingWriter, ItemGroup, ItemReason, ItemState
from ..models import DailyBriefing
from ..temporal.inputs import GENERATE_WORKFLOW_NAME, GenerateBriefingInputs, generate_workflow_id
from .content import BriefingContent
from .eligibility import briefing_day, resolve_timezone
from .fact_sheet import FactSheet, FactSheetItem, stored_fact_sheet

VIEW_STAMP_EVERY = timedelta(hours=1)

logger = structlog.get_logger(__name__)

_DELETED_REPORT_STATUS = "deleted"
_REPORT_STATES = {
    "resolved": ItemState.DONE,
    "suppressed": ItemState.DISMISSED,
    _DELETED_REPORT_STATUS: ItemState.DISMISSED,
}


def start_generation(briefing: DailyBriefing) -> None:
    """Start the generation workflow. The row keeps its status if Temporal is unreachable."""
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                GENERATE_WORKFLOW_NAME,
                GenerateBriefingInputs(team_id=briefing.team_id, briefing_id=str(briefing.id)),
                id=generate_workflow_id(str(briefing.id)),
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        )
    except Exception as error:
        logger.exception("today_generation_start_failed", briefing_id=str(briefing.id))
        capture_exception(error, {"briefing_id": str(briefing.id), "product": "today"})


def create_briefing(
    *, team: Team, user: User, local_day: date, timezone_name: str, trigger: BriefingTrigger
) -> DailyBriefing | None:
    """The new row, or None when a concurrent request created the day's pending row first."""
    try:
        with transaction.atomic():
            return DailyBriefing.objects.for_team(team.id).create(
                team_id=team.id,
                user_id=user.id,
                local_day=local_day,
                timezone=timezone_name,
                trigger=trigger,
                status=BriefingStatus.COLLECTING,
            )
    except IntegrityError:
        return None


def start_briefing(
    *, team: Team, user: User, local_day: date, timezone_name: str, trigger: BriefingTrigger
) -> DailyBriefing | None:
    """Create the day's row and start its run. None when another request started it a moment earlier."""
    briefing = create_briefing(team=team, user=user, local_day=local_day, timezone_name=timezone_name, trigger=trigger)
    if briefing is not None:
        start_generation(briefing)
    return briefing


@frozen
class CurrentBriefing:
    """What the page shows and whether something newer is on its way."""

    shown: DailyBriefing
    # A newer briefing is being written while the ready one is shown in its place.
    generating: bool


_PENDING = {BriefingStatus.COLLECTING, BriefingStatus.WRITING}


def _current(team: Team, user: User, local_day: date) -> CurrentBriefing | None:
    """The briefing to show for the day, and whether a newer one is being written.

    The newest ready briefing wins. While a refresh is still being written, the ready one stands
    in, so the person is never dropped back to the team list. With nothing ready, the one in
    progress is shown, and a failed one only when nothing else exists.
    """
    rows = list(
        DailyBriefing.objects.for_team(team.id).filter(user_id=user.id, local_day=local_day).order_by("-created_at")
    )
    if not rows:
        return None
    ready = next((row for row in rows if row.status == BriefingStatus.READY), None)
    pending = next((row for row in rows if row.status in _PENDING), None)
    shown = ready or pending or rows[0]
    return CurrentBriefing(shown=shown, generating=pending is not None and shown is not pending)


def get_or_start_briefing(
    *, team: Team, user: User, timezone_name: str | None, now: datetime | None = None
) -> CurrentBriefing:
    tz = resolve_timezone(timezone_name, team)
    day = briefing_day(now or timezone.now(), tz)
    current = _current(team, user, day)
    if current is None:
        # The scheduler writes the day's briefing ahead for recent viewers; this covers everyone else.
        briefing = start_briefing(
            team=team, user=user, local_day=day, timezone_name=tz, trigger=BriefingTrigger.FIRST_OPEN
        )
        if briefing is None:
            # Two tabs or a poll racing the first load: the request that lost the race shows the winner's row.
            return get_or_start_briefing(team=team, user=user, timezone_name=timezone_name, now=now)
        current = CurrentBriefing(shown=briefing, generating=False)
    now = timezone.now()
    # The scheduler only asks who viewed in the last few days, so the stamp does not need every poll.
    if current.shown.last_viewed_at is None or current.shown.last_viewed_at < now - VIEW_STAMP_EVERY:
        # Only a timezone the browser sent is worth keeping for the scheduler; an API call without one
        # must not move the person's mornings to the project timezone.
        stamp = {"last_viewed_at": now, "timezone": tz} if timezone_name else {"last_viewed_at": now}
        DailyBriefing.objects.for_team(team.id).filter(id=current.shown.id).update(**stamp)
    return current


def refresh_briefing(*, team: Team, user: User, timezone_name: str | None) -> DailyBriefing:
    """Regenerate today's briefing, unless one is already being written. The ready briefing stays
    on screen until the new one is written."""
    tz = resolve_timezone(timezone_name, team)
    day = briefing_day(timezone.now(), tz)
    current = _current(team, user, day)
    if current is not None and (current.generating or current.shown.status in _PENDING):
        return current.shown
    briefing = start_briefing(team=team, user=user, local_day=day, timezone_name=tz, trigger=BriefingTrigger.REFRESH)
    if briefing is None:
        # Another request started today's run between the read and the write; wait for that one.
        return refresh_briefing(team=team, user=user, timezone_name=timezone_name)
    return briefing


def delete_for_teams(team_ids: list[int]) -> None:
    DailyBriefing.objects.unscoped().filter(team_id__in=team_ids).delete()


def recent_ready_briefings(briefing: DailyBriefing, limit: int) -> list[DailyBriefing]:
    """The person's latest ready briefings before this one, newest first."""
    return list(
        DailyBriefing.objects.for_team(briefing.team_id)
        .filter(user_id=briefing.user_id, status=BriefingStatus.READY, created_at__lt=briefing.created_at)
        .order_by("-created_at")[:limit]
    )


def store_briefing(briefing: DailyBriefing, fact_sheet: FactSheet, content: BriefingContent) -> None:
    """Store the written briefing and show it."""
    briefing.facts = fact_sheet.model_dump(mode="json")
    briefing.content = content.model_dump(mode="json")
    briefing.writer = BriefingWriter.AGENT
    briefing.error = None
    briefing.status = BriefingStatus.READY
    briefing.ready_at = timezone.now()
    briefing.save(update_fields=["facts", "content", "writer", "error", "status", "ready_at"])


@frozen
class InboxCounts:
    """Open reports beyond the ones the page shows, counted now: the briefing itself is hours old."""

    more_for_you: int
    open_in_project: int


def _inbox_counts(team: Team, user: User, shown: list[FactSheetItem]) -> InboxCounts:
    shown_reports = [item.key.split(":", 1)[1] for item in shown if item.group == ItemGroup.REPORT]
    try:
        counts = signals.open_report_counts(
            team_id=team.id, user=user, exclude_report_ids=shown_reports, include_unowned=False
        )
    except Exception as error:
        capture_exception(error, {"team_id": team.id, "product": "today"})
        return InboxCounts(more_for_you=0, open_in_project=0)
    return InboxCounts(more_for_you=counts.for_person, open_in_project=counts.in_project)


def _report_details(
    team: Team, items: list[FactSheetItem], metric_access: signals.ReportMetricAccessPolicy
) -> dict[str, signals.BriefingReportDetails]:
    report_ids = [item.key.split(":", 1)[1] for item in items if item.key.startswith("report:")]
    if not report_ids:
        return {}
    try:
        details = signals.report_details(team_id=team.id, report_ids=report_ids, metric_access=metric_access)
    except Exception as error:
        capture_exception(error, {"team_id": team.id, "product": "today"})
        return {}
    return {f"report:{detail.report_id}": detail for detail in details}


def _live_states(reports: dict[str, signals.BriefingReportDetails]) -> dict[str, ItemState]:
    """Which reports were resolved or dismissed since the briefing was written."""
    return {key: _REPORT_STATES[detail.status] for key, detail in reports.items() if detail.status in _REPORT_STATES}


_NAMES_PERSON_REASONS = frozenset({ItemReason.WAITING_FOR_YOU, ItemReason.SUGGESTED_REVIEWER})


def _left_item_keys(team: Team, user: User, items: list[FactSheetItem], states: dict[str, ItemState]) -> set[str]:
    """Items the briefing picked because the report named the person, which it no longer does.

    The briefing is a saved list, so without this the report comes back on the next page load as
    though nothing happened. A report that already resolved or was dismissed keeps that state, which
    is the stronger thing to say about it.
    """
    candidates = {
        item.key: item.key.split(":", 1)[1]
        for item in items
        if item.key.startswith("report:") and item.reason in _NAMES_PERSON_REASONS and item.key not in states
    }
    if not candidates:
        return set()
    try:
        naming = signals.report_ids_naming_user(team_id=team.id, user=user, report_ids=list(candidates.values()))
    except Exception as error:
        # A failed lookup costs the label, not the briefing.
        capture_exception(error, {"team_id": team.id, "product": "today"})
        return set()
    return {key for key, report_id in candidates.items() if report_id not in naming}


def _report_contract(detail: signals.BriefingReportDetails) -> contracts.BriefingItemReport | None:
    # A deleted report keeps its state on the item, but none of its content, as in the Inbox.
    if detail.status == _DELETED_REPORT_STATUS:
        return None
    return contracts.BriefingItemReport(
        priority=detail.priority,
        summary=detail.summary,
        pull_request_state=detail.pull_request_state,
        pull_request_url=detail.pull_request_url,
        signal_count=detail.signal_count,
        updated_at=detail.updated_at,
        metrics=[
            contracts.BriefingItemMetric(
                metric_id=metric.metric_id,
                title=metric.title,
                kind=metric.kind,
                role=metric.role,
                value=metric.value,
                series=metric.series,
                value_format=metric.value_format,
                unit=metric.unit,
                query=metric.query,
            )
            for metric in detail.metrics
        ],
        charts=[
            contracts.BriefingItemChart(chart_id=chart.chart_id, title=chart.title, query=chart.query)
            for chart in detail.charts
        ],
    )


def to_contract(
    briefing: DailyBriefing,
    team: Team,
    user: User,
    *,
    metric_access: signals.ReportMetricAccessPolicy,
    status: BriefingStatus | None = None,
) -> contracts.Briefing:
    """The briefing as the page shows it: only the items the text names, with live states and counts.

    `status` overrides the row's own: while a newer briefing is being written, the
    page gets the last ready one as `writing`, so it keeps showing the text and keeps polling.
    `metric_access` is the viewer's access to report metrics, so the briefing hides what the Inbox hides.
    """
    fact_sheet = stored_fact_sheet(briefing)
    shown = fact_sheet.items if fact_sheet else []
    content = BriefingContent.model_validate(briefing.content or {})
    reports = _report_details(team, shown, metric_access)
    states = _live_states(reports)
    states |= dict.fromkeys(_left_item_keys(team, user, shown, states), ItemState.LEFT)
    counts = _inbox_counts(team, user, shown)
    return contracts.Briefing(
        id=str(briefing.id),
        status=status or BriefingStatus(briefing.status),
        writer=BriefingWriter(briefing.writer) if briefing.writer else None,
        local_day=briefing.local_day,
        headline=content.headline,
        paragraphs=[
            [
                contracts.BriefingSegment(text=segment.text, item_key=segment.item_key, highlight=segment.highlight)
                for segment in paragraph
            ]
            for paragraph in content.paragraphs
        ],
        items=[
            contracts.BriefingItem(
                key=item.key,
                group=item.group,
                source=item.source,
                reason=item.reason,
                title=item.title,
                label=content.labels.get(item.key) or item.title,
                signal=content.signals.get(item.key, ""),
                url=item.url,
                rank=item.rank,
                state=states.get(item.key, ItemState.OPEN),
                source_product=item.source_product,
                report=_report_contract(reports[item.key]) if item.key in reports else None,
            )
            for item in shown
        ],
        more_reports_count=counts.more_for_you,
        open_reports_count=counts.open_in_project,
        created_at=briefing.created_at,
        ready_at=briefing.ready_at,
    )


def _facts_to_candidates(fact_sheet: FactSheet, day: date, *, team: Team, user: User) -> contracts.CandidateList:
    counts = _inbox_counts(team, user, fact_sheet.items)
    return contracts.CandidateList(
        local_day=day,
        candidates=[
            contracts.Candidate(
                key=item.key,
                group=item.group,
                source=item.source,
                reason=item.reason,
                title=item.title,
                url=item.url,
                rank=item.rank,
                facts=[contracts.CandidateFact(name=name, value=value) for name, value in item.facts.items()],
            )
            for item in fact_sheet.items
        ],
        more_reports_count=counts.more_for_you,
    )


def list_candidates(*, team: Team, user: User, timezone_name: str | None) -> contracts.CandidateList:
    """The items behind today's briefing with their facts, or an empty list while it is being written."""
    tz = resolve_timezone(timezone_name, team)
    day = briefing_day(timezone.now(), tz)
    current = _current(team, user, day)
    fact_sheet = stored_fact_sheet(current.shown) if current is not None else None
    if fact_sheet is None:
        return contracts.CandidateList(local_day=day, candidates=[], more_reports_count=0)
    return _facts_to_candidates(fact_sheet, day, team=team, user=user)
