"""Reading and starting briefings for the API and the MCP tools."""

import asyncio
from datetime import date, datetime

from django.conf import settings
from django.utils import timezone

import structlog
from temporalio.common import WorkflowIDReusePolicy

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.temporal.common.client import sync_connect

from products.signals.backend.facade import api as signals

from ..facade import contracts
from ..facade.contracts import RefreshLimitReached
from ..facade.enums import BriefingEdition, BriefingStatus, BriefingTrigger, BriefingWriter, ItemGroup, ItemState
from ..models import DailyBriefing
from ..temporal.inputs import GENERATE_WORKFLOW_NAME, GenerateBriefingInputs, generate_workflow_id
from .candidates import SourceContext
from .content import BriefingContent
from .eligibility import EditionSlot, current_edition, resolve_timezone
from .fact_sheet import FactSheet, FactSheetItem, build_fact_sheet, stored_fact_sheet
from .ranking import rank_candidates, select
from .sources import collect_all

logger = structlog.get_logger(__name__)

MAX_REFRESHES_PER_DAY = 3
_DONE_REPORT_STATUSES = {"resolved", "suppressed", "deleted"}


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
    *, team: Team, user: User, slot: EditionSlot, timezone_name: str, trigger: BriefingTrigger
) -> DailyBriefing:
    return DailyBriefing.objects.for_team(team.id).create(
        team_id=team.id,
        user_id=user.id,
        local_day=slot.local_day,
        edition=slot.edition,
        timezone=timezone_name,
        trigger=trigger,
        status=BriefingStatus.COLLECTING,
    )


def _current(team: Team, user: User, slot: EditionSlot) -> DailyBriefing | None:
    """The edition's briefing: the newest ready one, else the newest in progress, else the newest failed one."""
    rows = list(
        DailyBriefing.objects.for_team(team.id)
        .filter(user_id=user.id, local_day=slot.local_day, edition=slot.edition)
        .order_by("-created_at")
    )
    pending_statuses = {BriefingStatus.COLLECTING, BriefingStatus.WRITING}
    ready = next((row for row in rows if row.status == BriefingStatus.READY), None)
    pending = next((row for row in rows if row.status in pending_statuses), None)
    return ready or pending or (rows[0] if rows else None)


def get_or_start_briefing(
    *, team: Team, user: User, timezone_name: str | None, now: datetime | None = None
) -> DailyBriefing:
    tz = resolve_timezone(timezone_name, team)
    slot = current_edition(now or timezone.now(), tz)
    briefing = _current(team, user, slot)
    if briefing is None:
        # The scheduler writes both editions ahead for recent viewers; this covers everyone else.
        briefing = create_briefing(
            team=team, user=user, slot=slot, timezone_name=tz, trigger=BriefingTrigger.FIRST_OPEN
        )
        start_generation(briefing)
    DailyBriefing.objects.for_team(team.id).filter(id=briefing.id).update(last_viewed_at=timezone.now(), timezone=tz)
    return briefing


def refresh_briefing(*, team: Team, user: User, timezone_name: str | None) -> DailyBriefing:
    """Regenerate the current edition. The ready briefing stays on screen until the new one is written."""
    tz = resolve_timezone(timezone_name, team)
    slot = current_edition(timezone.now(), tz)
    refreshes = (
        DailyBriefing.objects.for_team(team.id)
        .filter(user_id=user.id, local_day=slot.local_day, trigger=BriefingTrigger.REFRESH)
        .count()
    )
    if refreshes >= MAX_REFRESHES_PER_DAY:
        raise RefreshLimitReached()
    briefing = create_briefing(team=team, user=user, slot=slot, timezone_name=tz, trigger=BriefingTrigger.REFRESH)
    start_generation(briefing)
    return briefing


@frozen
class InboxCounts:
    """Open reports beyond the ones the page shows, counted now: the briefing itself is hours old."""

    more_for_you: int
    open_in_project: int


def _inbox_counts(team: Team, user: User, shown: list[FactSheetItem]) -> InboxCounts:
    if not shown:
        return InboxCounts(more_for_you=0, open_in_project=0)
    reports_shown = sum(1 for item in shown if item.group == ItemGroup.REPORT)
    try:
        counts = signals.open_report_counts(team_id=team.id, user=user)
    except Exception as error:
        capture_exception(error, {"team_id": team.id, "product": "today"})
        return InboxCounts(more_for_you=0, open_in_project=0)
    return InboxCounts(
        more_for_you=max(counts.for_person - reports_shown, 0),
        open_in_project=max(counts.in_project - reports_shown, 0),
    )


def _live_states(team: Team, items: list[FactSheetItem]) -> dict[str, ItemState]:
    report_ids = [item.key.split(":", 1)[1] for item in items if item.key.startswith("report:")]
    states: dict[str, ItemState] = {}
    try:
        for state in signals.report_states(team_id=team.id, report_ids=report_ids):
            if state.status in _DONE_REPORT_STATUSES:
                states[f"report:{state.report_id}"] = ItemState.DONE
    except Exception as error:
        capture_exception(error, {"team_id": team.id, "product": "today"})
    return states


def to_contract(briefing: DailyBriefing, team: Team, user: User) -> contracts.Briefing:
    """The briefing as the page shows it: only the items the text names, with live states and counts."""
    fact_sheet = stored_fact_sheet(briefing)
    shown = fact_sheet.text_items if fact_sheet else []
    content = BriefingContent.model_validate(briefing.content or briefing.draft or {})
    states = _live_states(team, shown)
    counts = _inbox_counts(team, user, shown)
    return contracts.Briefing(
        id=str(briefing.id),
        status=BriefingStatus(briefing.status),
        writer=BriefingWriter(briefing.writer) if briefing.writer else None,
        local_day=briefing.local_day,
        edition=BriefingEdition(briefing.edition),
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
            )
            for item in shown
        ],
        more_reports_count=counts.more_for_you,
        open_reports_count=counts.open_in_project,
        created_at=briefing.created_at,
        ready_at=briefing.ready_at,
    )


def _facts_to_candidates(fact_sheet: FactSheet, day: date, *, team: Team, user: User) -> contracts.CandidateList:
    counts = _inbox_counts(team, user, fact_sheet.text_items)
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
                in_text=item.in_text,
                facts=[
                    contracts.CandidateFact(name=name, value=str(value))
                    for name, value in item.facts.items()
                    if value is not None
                ],
            )
            for item in fact_sheet.items
        ],
        more_reports_count=counts.more_for_you,
        failed_sources=fact_sheet.failed_sources,
    )


def list_candidates(*, team: Team, user: User, timezone_name: str | None) -> contracts.CandidateList:
    """Today's ranked items with their facts: from today's briefing when there is one, else collected now."""
    tz = resolve_timezone(timezone_name, team)
    slot = current_edition(timezone.now(), tz)
    day = slot.local_day
    briefing = _current(team, user, slot)
    fact_sheet = stored_fact_sheet(briefing) if briefing is not None else None
    if fact_sheet is not None:
        return _facts_to_candidates(fact_sheet, day, team=team, user=user)
    ctx = SourceContext(team=team, user=user, now=timezone.now())
    collected = collect_all(ctx)
    fact_sheet = build_fact_sheet(
        first_name=user.first_name,
        local_day=day,
        items=select(rank_candidates(collected.candidates)),
        failed_sources=collected.failed_sources,
    )
    return _facts_to_candidates(fact_sheet, day, team=team, user=user)
