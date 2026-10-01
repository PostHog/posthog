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
from ..facade.enums import BriefingEdition, BriefingStatus, BriefingTrigger, BriefingWriter, ItemGroup, ItemState
from ..models import DailyBriefing
from ..temporal.inputs import GENERATE_WORKFLOW_NAME, GenerateBriefingInputs, generate_workflow_id
from .content import BriefingContent
from .eligibility import EditionSlot, current_edition, resolve_timezone
from .fact_sheet import FactSheet, FactSheetItem, stored_fact_sheet

VIEW_STAMP_EVERY = timedelta(hours=1)

logger = structlog.get_logger(__name__)

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
) -> DailyBriefing | None:
    """The new row, or None when a concurrent request created the edition's pending row first."""
    try:
        with transaction.atomic():
            return DailyBriefing.objects.for_team(team.id).create(
                team_id=team.id,
                user_id=user.id,
                local_day=slot.local_day,
                edition=slot.edition,
                timezone=timezone_name,
                trigger=trigger,
                status=BriefingStatus.COLLECTING,
            )
    except IntegrityError:
        return None


def start_briefing(
    *, team: Team, user: User, slot: EditionSlot, timezone_name: str, trigger: BriefingTrigger
) -> DailyBriefing | None:
    """Create the edition's row and start its run. None when another request started it a moment earlier."""
    briefing = create_briefing(team=team, user=user, slot=slot, timezone_name=timezone_name, trigger=trigger)
    if briefing is not None:
        start_generation(briefing)
    return briefing


@frozen
class CurrentBriefing:
    """What the page shows and whether something newer is on its way."""

    shown: DailyBriefing
    # A briefing for this edition is being written while an earlier ready one is shown in its place.
    generating: bool


_PENDING = {BriefingStatus.COLLECTING, BriefingStatus.WRITING}


def _current(team: Team, user: User, slot: EditionSlot) -> CurrentBriefing | None:
    """The briefing to show for the edition, and whether a newer one is being written.

    The newest ready briefing of the edition wins. While the edition's briefing is still being
    written, the day's latest ready one stands in, so a refresh or the noon edition never drops
    the person back to the team list. With nothing ready today, the one in progress is shown, and
    a failed one only when nothing else exists.
    """
    rows = list(
        DailyBriefing.objects.for_team(team.id)
        .filter(user_id=user.id, local_day=slot.local_day)
        .order_by("-created_at")
    )
    edition_rows = [row for row in rows if row.edition == slot.edition]
    if not edition_rows:
        return None
    ready = next((row for row in edition_rows if row.status == BriefingStatus.READY), None)
    pending = next((row for row in edition_rows if row.status in _PENDING), None)
    if ready is not None and (pending is None or pending.created_at < ready.created_at):
        return CurrentBriefing(shown=ready, generating=False)
    earlier_ready = next((row for row in rows if row.status == BriefingStatus.READY), None)
    shown = earlier_ready or pending or edition_rows[0]
    return CurrentBriefing(shown=shown, generating=pending is not None and shown is not pending)


def get_or_start_briefing(
    *, team: Team, user: User, timezone_name: str | None, now: datetime | None = None
) -> CurrentBriefing:
    tz = resolve_timezone(timezone_name, team)
    slot = current_edition(now or timezone.now(), tz)
    current = _current(team, user, slot)
    if current is None:
        # The scheduler writes both editions ahead for recent viewers; this covers everyone else.
        briefing = start_briefing(team=team, user=user, slot=slot, timezone_name=tz, trigger=BriefingTrigger.FIRST_OPEN)
        if briefing is None:
            # Two tabs or a poll racing the first load: the request that lost the race shows the winner's row.
            return get_or_start_briefing(team=team, user=user, timezone_name=timezone_name, now=now)
        current = CurrentBriefing(shown=briefing, generating=False)
    now = timezone.now()
    # The scheduler only asks who viewed in the last 14 days, so the stamp does not need every poll.
    if current.shown.last_viewed_at is None or current.shown.last_viewed_at < now - VIEW_STAMP_EVERY:
        DailyBriefing.objects.for_team(team.id).filter(id=current.shown.id).update(last_viewed_at=now, timezone=tz)
    return current


def refresh_briefing(*, team: Team, user: User, timezone_name: str | None) -> DailyBriefing:
    """Regenerate the current edition, unless one is already being written. The ready briefing stays
    on screen until the new one is written."""
    tz = resolve_timezone(timezone_name, team)
    slot = current_edition(timezone.now(), tz)
    current = _current(team, user, slot)
    if current is not None and (current.generating or current.shown.status in _PENDING):
        return current.shown
    briefing = start_briefing(team=team, user=user, slot=slot, timezone_name=tz, trigger=BriefingTrigger.REFRESH)
    if briefing is None:
        # Another request started this edition's run between the read and the write; wait for that one.
        return refresh_briefing(team=team, user=user, timezone_name=timezone_name)
    return briefing


def recent_ready_briefings(briefing: DailyBriefing, limit: int) -> list[DailyBriefing]:
    """The person's latest ready briefings before this one, newest first."""
    return list(
        DailyBriefing.objects.for_team(briefing.team_id)
        .filter(user_id=briefing.user_id, status=BriefingStatus.READY, created_at__lt=briefing.created_at)
        .order_by("-created_at")[:limit]
    )


def store_briefing(briefing: DailyBriefing, fact_sheet: FactSheet, content: BriefingContent) -> None:
    """Store what the agent wrote and show it."""
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


def to_contract(
    briefing: DailyBriefing, team: Team, user: User, *, status: BriefingStatus | None = None
) -> contracts.Briefing:
    """The briefing as the page shows it: only the items the text names, with live states and counts.

    `status` overrides the row's own: while a newer briefing for the edition is being written, the
    page gets the last ready one as `writing`, so it keeps showing the text and keeps polling.
    """
    fact_sheet = stored_fact_sheet(briefing)
    shown = fact_sheet.items if fact_sheet else []
    content = BriefingContent.model_validate(briefing.content or {})
    states = _live_states(team, shown)
    counts = _inbox_counts(team, user, shown)
    return contracts.Briefing(
        id=str(briefing.id),
        status=status or BriefingStatus(briefing.status),
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
    slot = current_edition(timezone.now(), tz)
    current = _current(team, user, slot)
    fact_sheet = stored_fact_sheet(current.shown) if current is not None else None
    if fact_sheet is None:
        return contracts.CandidateList(local_day=slot.local_day, candidates=[], more_reports_count=0)
    return _facts_to_candidates(fact_sheet, slot.local_day, team=team, user=user)
