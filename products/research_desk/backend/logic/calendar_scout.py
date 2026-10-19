import re
from datetime import datetime, timedelta

from posthog.dataclasses import frozen

from products.customer_analytics.backend.facade import api as customer_analytics_api
from products.customer_analytics.backend.facade.contracts import SyncedMeeting

from ..facade import contracts
from ..facade.enums import SessionOrigin, SessionStatus
from .emails import email_domain, normalize_email
from .sessions import upsert_session

LOOKBACK = timedelta(days=2)
LOOKAHEAD = timedelta(days=14)
RESEARCH_TITLE_PATTERN = re.compile(
    r"\b(interviews?|user research|research call|research chat|user chat|customer chat|feedback (?:call|chat|session))\b",
    re.IGNORECASE,
)


@frozen
class CalendarScoutCounts:
    meetings: int
    sessions_created: int
    sessions_updated: int


def is_research_meeting(title: str) -> bool:
    return bool(RESEARCH_TITLE_PATTERN.search(title))


def _session_status(meeting: SyncedMeeting, now: datetime) -> SessionStatus:
    if meeting.status == "cancelled":
        return SessionStatus.CANCELLED
    end = meeting.end_time or meeting.start_time
    return SessionStatus.HELD if end <= now else SessionStatus.SCHEDULED


def session_input_for_meeting(
    team_id: int, meeting: SyncedMeeting, now: datetime
) -> contracts.UpsertResearchSessionInput | None:
    """Map a synced meeting to a session, or None when it is not customer research."""
    if not is_research_meeting(meeting.title):
        return None
    organizer = normalize_email(meeting.organizer_email)
    if "@" not in organizer:
        return None
    internal_domain = email_domain(organizer)
    emails = [normalize_email(p.email) for p in meeting.participants]
    internal = [e for e in emails if email_domain(e) == internal_domain]
    external = [e for e in emails if "@" in e and email_domain(e) != internal_domain]
    if not external:
        return None
    return contracts.UpsertResearchSessionInput(
        team_id=team_id,
        origin=SessionOrigin.CALENDAR,
        external_ref=str(meeting.id),
        start_time=meeting.start_time,
        end_time=meeting.end_time,
        status=_session_status(meeting, now),
        title=meeting.title,
        organizer_email=organizer,
        internal_emails=tuple(internal),
        external_emails=tuple(external),
        meeting_url=f"https://meet.google.com/{meeting.meet_code}" if meeting.meet_code else "",
    )


def sync_sessions_from_calendar(team_id: int, *, now: datetime) -> CalendarScoutCounts:
    meetings = customer_analytics_api.list_meetings_in_window(
        team_id, start_after=now - LOOKBACK, start_before=now + LOOKAHEAD
    )
    created = updated = 0
    for meeting in meetings:
        data = session_input_for_meeting(team_id, meeting, now)
        if data is None:
            continue
        _, was_created = upsert_session(data)
        if was_created:
            created += 1
        else:
            updated += 1
    return CalendarScoutCounts(meetings=len(meetings), sessions_created=created, sessions_updated=updated)
