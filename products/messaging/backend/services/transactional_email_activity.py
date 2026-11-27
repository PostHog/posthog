"""What the recipient of one email did in the product around the send."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlparse
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.domain_connect import organizational_domain
from posthog.models import Team, User
from posthog.models.person.util import get_person_by_distinct_id

from products.messaging.backend.facade.contracts import (
    EmailClickNoSessionReason,
    EmailLogEventKind,
    TransactionalEmailActivity,
    TransactionalEmailActivityEvent,
    TransactionalEmailActivitySession,
    TransactionalEmailClick,
    TransactionalEmailClickSession,
    TransactionalEmailLogDetail,
    TransactionalEmailOwnEvent,
    TransactionalEmailSendActivity,
)
from products.messaging.backend.models.email_status_sql import EMAIL_STATUS_TTL_DAYS
from products.messaging.backend.services.transactional_email_log import get_transactional_email, tagged_landing
from products.workflows.backend.facade.api import is_email_workflow_run_link_tag_enabled
from products.workflows.backend.facade.contracts import WorkflowViewAccess

ACTIVITY_WINDOW_DAYS = 7
ACTIVITY_BEFORE_LIMIT = 50
ACTIVITY_AFTER_LIMIT = 100
MAX_DISTINCT_IDS = 100
MAX_OWN_EVENTS_PER_KIND = 100
MAX_LANDINGS = 100
CLICK_EVENT = "$workflows_email_link_clicked"
OWN_EVENTS = ("$workflows_email_sent", "$workflows_email_delivered", "$workflows_email_opened", CLICK_EVENT)
CLOCK_SKEW = timedelta(minutes=2)
LANDING_AFTER_CLICK = timedelta(minutes=30)
SESSION_SPAN = timedelta(days=1)

# Events that describe the SDK rather than something the person did.
HIDDEN_EVENTS = (
    "$feature_flag_called",
    "$identify",
    "$set",
    "$groupidentify",
    "$create_alias",
    "$pageleave",
    "$web_vitals",
    "$opt_in",
    "$autocapture_disabled",
    "$dead_click",
    "$exception",
    "$feature_view",
    "$feature_interaction",
    "$snapshot",
    # The send's own timeline already covers these.
    "$workflows_email_sent",
    "$workflows_email_failed",
    "$workflows_email_delivered",
    "$workflows_email_opened",
    "$workflows_email_link_clicked",
    "$workflows_email_bounced",
    "$workflows_email_blocked",
)


def get_transactional_email_activity(
    team: Team,
    user: User | None,
    message_id: UUID,
    *,
    access: WorkflowViewAccess | None = None,
) -> TransactionalEmailSendActivity | None:
    """The recipient's events in the week before and after one send, and each click with the session it started, or
    None when the reader can't see the send."""
    detail = get_transactional_email(team.id, message_id, access=access)
    if detail is None:
        return None
    sent_at = next(
        (event.at for event in detail.timeline if event.kind == EmailLogEventKind.SENT), detail.entry.created_at
    )
    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    own_events = _own_events(team, user, detail)
    return TransactionalEmailSendActivity(
        recipient=get_email_activity(team, user, detail.distinct_id, sent_at),
        clicks=_clicks(team, user, detail, own_events),
        email_events=[
            TransactionalEmailOwnEvent(uuid=event.uuid, event=event.event, timestamp=event.timestamp)
            for event in own_events
        ],
    )


def get_email_activity(
    team: Team, user: User | None, distinct_id: str, sent_at: datetime
) -> TransactionalEmailActivity:
    """The events of the person behind `distinct_id` in the week before and after `sent_at`."""
    if not distinct_id:
        return TransactionalEmailActivity(
            distinct_id="",
            sent_at=sent_at,
            before=[],
            after=[],
            has_more_before=False,
            has_more_after=False,
            sessions=[],
        )

    tag_queries(product=Product.MESSAGING, feature=Feature.QUERY)
    window = timedelta(days=ACTIVITY_WINDOW_DAYS)
    recipient = _recipient_match(team.id, distinct_id)
    before = _events(team, user, recipient, sent_at - window, sent_at, newest_first=True, limit=ACTIVITY_BEFORE_LIMIT)
    after = _events(team, user, recipient, sent_at, sent_at + window, newest_first=False, limit=ACTIVITY_AFTER_LIMIT)
    shown_before = list(reversed(before[:ACTIVITY_BEFORE_LIMIT]))
    shown_after = after[:ACTIVITY_AFTER_LIMIT]
    shown_before_sessions = {event.session_id for event in shown_before if event.session_id}
    started_before = shown_before_sessions | _sessions_with_events_in(
        team,
        user,
        recipient,
        sent_at - window,
        sent_at,
        {event.session_id for event in shown_after if event.session_id} - shown_before_sessions,
    )
    return TransactionalEmailActivity(
        distinct_id=distinct_id,
        sent_at=sent_at,
        before=shown_before,
        after=shown_after,
        has_more_before=len(before) > ACTIVITY_BEFORE_LIMIT,
        has_more_after=len(after) > ACTIVITY_AFTER_LIMIT,
        sessions=_sessions(shown_before, shown_after, started_before),
    )


def _recipient_match(team_id: int, distinct_id: str) -> ast.Expr:
    # A recipient without a person profile still has events under the send's own distinct ID.
    person = get_person_by_distinct_id(team_id, distinct_id, distinct_id_limit=MAX_DISTINCT_IDS)
    distinct_ids = person.distinct_ids if person else []
    if len(distinct_ids) >= MAX_DISTINCT_IDS:
        # The list may be cut short, so match every ID of the person instead.
        return parse_expr(
            "person_id IN (SELECT person_id FROM person_distinct_ids WHERE distinct_id = {distinct_id})",
            placeholders={"distinct_id": ast.Constant(value=distinct_id)},
        )
    others = [other for other in distinct_ids if other != distinct_id]
    return parse_expr(
        "distinct_id IN {distinct_ids}", placeholders={"distinct_ids": ast.Constant(value=[distinct_id, *others])}
    )


def _events(
    team: Team,
    user: User | None,
    recipient: ast.Expr,
    start: datetime,
    end: datetime,
    *,
    newest_first: bool,
    limit: int,
) -> list[TransactionalEmailActivityEvent]:
    # One row past the limit tells the caller there is more.
    response = execute_hogql_query(
        f"""
        SELECT uuid, event, timestamp, properties.$current_url, properties.$pathname, properties.$session_id,
               properties.$event_type, elements_chain
        FROM events
        WHERE {{recipient}}
          AND timestamp >= {{start}} AND timestamp < {{end}}
          AND event NOT IN {{hidden}}
        ORDER BY timestamp {"DESC" if newest_first else "ASC"}
        LIMIT {{limit}}
        """,
        team=team,
        user=user,
        placeholders={
            "recipient": clone_expr(recipient),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "hidden": ast.Constant(value=list(HIDDEN_EVENTS)),
            "limit": ast.Constant(value=limit + 1),
        },
        query_type="transactional_email_activity",
        workload=Workload.ONLINE,
    )
    return [
        TransactionalEmailActivityEvent(
            uuid=str(uuid),
            event=event,
            timestamp=timestamp.astimezone(UTC),
            current_url=current_url or None,
            pathname=pathname or None,
            session_id=session_id or None,
            event_type=event_type or None,
            elements_chain=elements_chain or "",
        )
        for uuid, event, timestamp, current_url, pathname, session_id, event_type, elements_chain in response.results
        or []
    ]


def _sessions_with_events_in(
    team: Team,
    user: User | None,
    recipient: ast.Expr,
    start: datetime,
    end: datetime,
    session_ids: set[str],
) -> set[str]:
    # The shown events leave out hidden events and anything past the cap, so they can't say when a session started.
    if not session_ids:
        return set()
    response = execute_hogql_query(
        """
        SELECT DISTINCT properties.$session_id
        FROM events
        WHERE {recipient}
          AND timestamp >= {start} AND timestamp < {end}
          AND properties.$session_id IN {session_ids}
        """,
        team=team,
        user=user,
        placeholders={
            "recipient": clone_expr(recipient),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
            "session_ids": ast.Constant(value=sorted(session_ids)),
        },
        query_type="transactional_email_activity_sessions",
        workload=Workload.ONLINE,
    )
    return {session_id for (session_id,) in response.results or []}


def _sessions(
    before: list[TransactionalEmailActivityEvent],
    after: list[TransactionalEmailActivityEvent],
    started_before: set[str],
) -> list[TransactionalEmailActivitySession]:
    events_by_session: dict[str, list[TransactionalEmailActivityEvent]] = {}
    for event in [*before, *after]:
        if event.session_id:
            events_by_session.setdefault(event.session_id, []).append(event)
    return [
        TransactionalEmailActivitySession(
            session_id=session_id,
            first_event_at=events[0].timestamp,
            last_event_at=events[-1].timestamp,
            event_count=len(events),
            started_after_send=session_id not in started_before,
        )
        for session_id, events in events_by_session.items()
    ]


@frozen
class _OwnEvent:
    uuid: str
    event: str
    timestamp: datetime
    link_url: str | None


def _own_events(team: Team, user: User | None, detail: TransactionalEmailLogDetail) -> list[_OwnEvent]:
    if not detail.distinct_id:
        return []
    queued_at = detail.entry.created_at
    response = execute_hogql_query(
        """
        SELECT uuid, event, timestamp, properties.$link_url
        FROM events
        WHERE event IN {events}
          AND distinct_id = {distinct_id}
          AND properties.$workflow_invocation_id = {message_id}
          AND timestamp >= {start} AND timestamp < {end}
        ORDER BY timestamp
        LIMIT {limit} BY event
        """,
        team=team,
        user=user,
        placeholders={
            "events": ast.Constant(value=list(OWN_EVENTS)),
            "distinct_id": ast.Constant(value=detail.distinct_id),
            "message_id": ast.Constant(value=detail.entry.message_id),
            "start": ast.Constant(value=queued_at - CLOCK_SKEW),
            "end": ast.Constant(value=queued_at + timedelta(days=EMAIL_STATUS_TTL_DAYS)),
            "limit": ast.Constant(value=MAX_OWN_EVENTS_PER_KIND),
        },
        query_type="transactional_email_activity_own_events",
        workload=Workload.ONLINE,
    )
    return [
        _OwnEvent(uuid=str(uuid), event=event, timestamp=timestamp.astimezone(UTC), link_url=link_url or None)
        for uuid, event, timestamp, link_url in response.results or []
    ]


def _clicks(
    team: Team, user: User | None, detail: TransactionalEmailLogDetail, own_events: list[_OwnEvent]
) -> list[TransactionalEmailClick]:
    click_times = [event.at for event in detail.timeline if event.kind == EmailLogEventKind.CLICKED]
    if not click_times:
        return []
    click_events: dict[datetime, list[_OwnEvent]] = {}
    for event in own_events:
        if event.event == CLICK_EVENT:
            click_events.setdefault(event.timestamp, []).append(event)
    events = [click_events[at].pop(0) if click_events.get(at) else None for at in click_times]
    links = [event.link_url if event else None for event in events]
    sending_domain = detail.entry.sending_domain
    sessions = _sessions_by_click(
        click_times,
        links,
        [_is_off_site(link_url, sending_domain) for link_url in links],
        _landings(team, user, detail.entry.message_id, click_times),
    )
    link_tagging_enabled = is_email_workflow_run_link_tag_enabled(team_id=team.id)
    return [
        TransactionalEmailClick(
            at=at,
            link_url=link_url,
            event_uuid=event.uuid if event else None,
            session=sessions.get(index),
            no_session_reason=None
            if index in sessions
            else _no_session_reason(link_url, link_tagging_enabled, sending_domain, detail.sensitive),
        )
        for index, (at, event, link_url) in enumerate(zip(click_times, events, links))
    ]


def _landings(
    team: Team, user: User | None, message_id: str, click_times: list[datetime]
) -> list[TransactionalEmailClickSession]:
    response = execute_hogql_query(
        """
        SELECT
            $session_id,
            min(timestamp) AS landed_at,
            argMin(properties.$current_url, timestamp),
            argMin(properties.$device_type, timestamp),
            argMin(properties.$browser, timestamp),
            argMin(properties.$geoip_city_name, timestamp)
        FROM events
        WHERE {tagged_landing} AND {in_click_windows}
        GROUP BY $session_id
        ORDER BY landed_at
        LIMIT {limit}
        """,
        team=team,
        user=user,
        placeholders={
            "tagged_landing": tagged_landing([message_id]),
            "in_click_windows": _in_click_windows(click_times),
            "limit": ast.Constant(value=MAX_LANDINGS),
        },
        query_type="transactional_email_activity_landings",
        workload=Workload.ONLINE,
    )
    landings = response.results or []
    stats = _session_stats(
        team,
        user,
        [row[0] for row in landings],
        min(row[1] for row in landings) - SESSION_SPAN if landings else click_times[0],
        max(row[1] for row in landings) + timedelta(seconds=1) if landings else click_times[-1],
    )
    return [
        TransactionalEmailClickSession(
            session_id=session_id,
            landed_at=landed_at.astimezone(UTC),
            landing_url=landing_url,
            duration_seconds=stats.get(session_id, (None, None))[0],
            pageview_count=stats.get(session_id, (None, None))[1],
            device_type=device_type or None,
            browser=browser or None,
            city=city or None,
        )
        for session_id, landed_at, landing_url, device_type, browser, city in landings
    ]


def _in_click_windows(click_times: list[datetime]) -> ast.Expr:
    windows: list[tuple[datetime, datetime]] = []
    for at in click_times:
        start, end = at - CLOCK_SKEW, at + LANDING_AFTER_CLICK
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    return ast.Or(
        exprs=[
            ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=start),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Lt, left=ast.Field(chain=["timestamp"]), right=ast.Constant(value=end)
                    ),
                ]
            )
            for start, end in windows
        ]
    )


def _session_stats(
    team: Team, user: User | None, session_ids: list[str], start: datetime, end: datetime
) -> dict[str, tuple[int | None, int | None]]:
    if not session_ids:
        return {}
    response = execute_hogql_query(
        """
        SELECT session_id, $session_duration, $pageview_count
        FROM sessions
        WHERE session_id IN {session_ids} AND $start_timestamp >= {start} AND $start_timestamp < {end}
        """,
        team=team,
        user=user,
        placeholders={
            "session_ids": ast.Constant(value=session_ids),
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
        },
        query_type="transactional_email_activity_session_stats",
        workload=Workload.ONLINE,
    )
    return {str(session_id): (duration, pageviews) for session_id, duration, pageviews in response.results or []}


def _sessions_by_click(
    click_times: list[datetime],
    links: list[str | None],
    off_site: list[bool],
    landings: list[TransactionalEmailClickSession],
) -> dict[int, TransactionalEmailClickSession]:
    sessions: dict[int, TransactionalEmailClickSession] = {}
    for landing in landings:
        eligible = [
            index
            for index, at in enumerate(click_times)
            if not off_site[index] and at - CLOCK_SKEW <= landing.landed_at <= at + LANDING_AFTER_CLICK
        ]
        same_page = [index for index in eligible if _lands_on(links[index], landing.landing_url)]
        free = [index for index in same_page or eligible if index not in sessions]
        if free and (same_page or len(free) == 1):
            sessions[_started_by(free, click_times, landing.landed_at)] = landing
    return sessions


def _started_by(indexes: list[int], click_times: list[datetime], landed_at: datetime) -> int:
    before = [index for index in indexes if click_times[index] <= landed_at]
    return before[-1] if before else indexes[0]


def _lands_on(link_url: str | None, landing_url: str) -> bool:
    link, landing = _url(link_url), _url(landing_url)
    return bool(
        link
        and landing
        and link.host == landing.host
        and link.path == landing.path
        and set(link.params) <= set(landing.params)
    )


@frozen
class _Url:
    host: str
    path: str
    params: list[tuple[str, str]]


def _url(url: str | None) -> _Url | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    return _Url(host=host, path=parsed.path.rstrip("/"), params=parse_qsl(parsed.query, keep_blank_values=True))


def _is_off_site(link_url: str | None, sending_domain: str) -> bool:
    link = _url(link_url)
    return bool(
        link
        and link.host
        and sending_domain
        and organizational_domain(link.host) != organizational_domain(sending_domain)
    )


def _no_session_reason(
    link_url: str | None, link_tagging_enabled: bool, sending_domain: str, sensitive: bool
) -> EmailClickNoSessionReason:
    if _is_off_site(link_url, sending_domain):
        return EmailClickNoSessionReason.OFF_SITE
    link = _url(link_url)
    if sensitive and link and not link.path:
        return EmailClickNoSessionReason.SENSITIVE
    if not link_tagging_enabled:
        return EmailClickNoSessionReason.LINK_TAGGING_OFF
    if not link_url:
        return EmailClickNoSessionReason.LINK_UNKNOWN
    return EmailClickNoSessionReason.NOT_FOUND
