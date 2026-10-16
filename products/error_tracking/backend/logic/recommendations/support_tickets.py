from datetime import UTC, datetime, timedelta
from typing import Any

from django.utils import timezone

import structlog

from posthog.schema import ProductKey

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from .impact_lens import MAX_ISSUES, ImpactLens, issue_state_join, with_issue_details
from .known_patterns import noise_issue_ids

logger = structlog.get_logger(__name__)

WINDOW_DAYS = 30
BEFORE_TICKET_MINUTES = 5
MIN_TICKETS = 2
MIN_LIFT = 3.0
MAX_TICKETS_PER_TEAM = 5000

# The total counts every matching ticket, so the baseline rate stays right for a team above the row limit.
TICKETS_QUERY = """
    SELECT id, ticket_number, session_id, created_at, count() OVER () AS total
    FROM system.support_tickets
    WHERE channel_source = 'widget'
        AND session_id IS NOT NULL
        AND session_id != ''
        AND created_at >= now() - toIntervalDay({window_days})
    ORDER BY created_at DESC
    LIMIT {limit}
"""

# The issues seen in each ticket's session in the minutes before the ticket.
LINKED_QUERY = """
    WITH tickets AS (
        SELECT
            toInt64(tupleElement(ticket, 1)) AS team_id,
            tupleElement(ticket, 2) AS ticket_id,
            tupleElement(ticket, 3) AS session_id,
            toDateTime64(tupleElement(ticket, 4), 6, 'UTC') AS ticket_at
        FROM (
            SELECT arrayJoin(
                arrayZip(%(ticket_team_ids)s, %(ticket_ids)s, %(ticket_sessions)s, %(ticket_times)s)
            ) AS ticket
        )
    )
    SELECT exceptions.team_id AS team_id, exceptions.issue_id AS issue_id, groupUniqArray(tickets.ticket_id) AS ticket_ids
    FROM (
        SELECT
            events.team_id AS team_id,
            toString(issue_state.issue_id) AS issue_id,
            events.`$session_id` AS session_id,
            events.timestamp AS ts
        FROM events
        {issue_state_join}
        WHERE events.team_id IN %(team_ids)s
            AND events.event = '$exception'
            AND events.timestamp >= now() - toIntervalDay(%(window_days)s + 1)
            AND events.`$session_id` IN %(session_ids)s
            AND issue_state.issue_status = 'active'
    ) AS exceptions
    INNER JOIN tickets ON exceptions.team_id = tickets.team_id AND exceptions.session_id = tickets.session_id
    WHERE exceptions.ts >= tickets.ticket_at - toIntervalMinute(%(before_ticket_minutes)s)
        AND exceptions.ts <= tickets.ticket_at
    GROUP BY team_id, issue_id
"""

# The 30-day sessions of the linked issues, and each team's pageview sessions for the baseline rate.
SESSIONS_QUERY = """
    SELECT 'issue' AS kind, events.team_id AS team_id, toString(issue_state.issue_id) AS issue_id, uniq(events.`$session_id`) AS sessions
    FROM events
    {issue_state_join}
    WHERE events.team_id IN %(team_ids)s
        AND events.event = '$exception'
        AND events.timestamp >= now() - toIntervalDay(%(window_days)s)
        AND events.`$session_id` != ''
        AND (events.team_id, toString(issue_state.issue_id)) IN %(linked_issues)s
    GROUP BY team_id, issue_id
    UNION ALL
    SELECT 'baseline' AS kind, team_id, '' AS issue_id, uniq(`$session_id`) AS sessions
    FROM events
    WHERE team_id IN %(team_ids)s
        AND event = '$pageview'
        AND timestamp >= now() - toIntervalDay(%(window_days)s)
        AND `$session_id` != ''
    GROUP BY team_id
"""


@frozen
class Ticket:
    id: str
    number: int
    session_id: str
    created_at: datetime


def _utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC) if moment.tzinfo else moment


def per_thousand(tickets: int, sessions: int) -> float:
    return tickets / sessions * 1000 if sessions else 0.0


def find_ticket_issues(
    linked: dict[str, list[str]],
    issue_sessions: dict[str, int],
    ticket_numbers: dict[str, int],
    baseline_per_1k: float,
) -> list[dict[str, Any]]:
    """Pick the issues after which people open support tickets far more often than the team's usual rate.

    ``linked`` maps an issue id to the ids of tickets opened within minutes after it in the same session.
    ``issue_sessions`` maps an issue id to its sessions in the window.
    """
    issues: list[dict[str, Any]] = []
    for issue_id, ticket_ids in linked.items():
        tickets = len(ticket_ids)
        sessions = issue_sessions.get(issue_id, 0)
        rate = per_thousand(tickets, sessions)
        if tickets < MIN_TICKETS or sessions == 0 or rate < MIN_LIFT * baseline_per_1k:
            continue
        newest_first = sorted(ticket_ids, key=lambda ticket_id: -ticket_numbers.get(ticket_id, 0))
        refs = [{"id": ticket_id, "number": ticket_numbers.get(ticket_id, 0)} for ticket_id in newest_first]
        issues.append(
            {"id": issue_id, "tickets": tickets, "sessions": sessions, "per_1k": round(rate, 2), "ticket_refs": refs}
        )
    return sorted(issues, key=lambda i: -i["per_1k"])[:MAX_ISSUES]


@frozen
class TeamTickets:
    """The newest widget tickets with a session, and how many matched in total, which can exceed the list's limit."""

    tickets: list[Ticket]
    total: int


def _fetch_tickets(team: Team) -> TeamTickets | None:
    """Widget tickets with a session id, or None when the team cannot read support tickets.

    HogQL scopes system.support_tickets to one team, so this runs once per team. Each query reads only that team's
    tickets in the window and returns a bounded list.
    """
    try:
        context = HogQLContext(
            team_id=team.pk,
            database=Database.create_for(team=team, allowed_system_tables=["support_tickets"]),
        )
        response = execute_hogql_query(
            query=parse_select(TICKETS_QUERY.format(window_days=WINDOW_DAYS, limit=MAX_TICKETS_PER_TEAM)),
            team=team,
            context=context,
            query_type="ErrorTrackingSupportTicketsLens",
            workload=Workload.OFFLINE,
        )
    except Exception:
        logger.warning("error_tracking_support_tickets_fetch_failed", team_id=team.id, exc_info=True)
        return None
    rows = response.results or []
    return TeamTickets(
        tickets=[Ticket(id=str(row[0]), number=int(row[1]), session_id=str(row[2]), created_at=row[3]) for row in rows],
        total=int(rows[0][4]) if rows else 0,
    )


class SupportTicketsRecommendation(ImpactLens):
    type = "support_tickets"
    refresh_interval = timedelta(hours=6)

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        tag_queries(
            product=ProductKey.ERROR_TRACKING,
            feature=Feature.ENRICHMENT,
            name="recommendations:support_tickets",
        )
        tickets_by_team: dict[int, TeamTickets] = {}
        for team in Team.objects.filter(id__in=team_ids):
            team_tickets = _fetch_tickets(team)
            if team_tickets and team_tickets.tickets:
                tickets_by_team[team.id] = team_tickets

        metas: dict[int, dict[str, Any]] = {
            team_id: {
                "window_days": WINDOW_DAYS,
                "evaluable": team_id in tickets_by_team,
                "tickets": tickets_by_team[team_id].total if team_id in tickets_by_team else 0,
                "tickets_with_errors": 0,
                "baseline_per_1k": 0.0,
                "issues": [],
            }
            for team_id in team_ids
        }
        if not tickets_by_team:
            return metas

        all_tickets = [(team_id, ticket) for team_id, team in tickets_by_team.items() for ticket in team.tickets]
        team_ids_with_tickets = sorted(tickets_by_team)
        linked: dict[int, dict[str, list[str]]] = {}
        for team_id, issue_id, ticket_ids in sync_execute(
            LINKED_QUERY.format(issue_state_join=issue_state_join()),
            {
                "team_ids": team_ids_with_tickets,
                "window_days": WINDOW_DAYS,
                "before_ticket_minutes": BEFORE_TICKET_MINUTES,
                "session_ids": sorted({ticket.session_id for _, ticket in all_tickets}),
                "ticket_team_ids": [team_id for team_id, _ in all_tickets],
                "ticket_ids": [ticket.id for _, ticket in all_tickets],
                "ticket_sessions": [ticket.session_id for _, ticket in all_tickets],
                "ticket_times": [_utc(ticket.created_at).strftime("%Y-%m-%d %H:%M:%S.%f") for _, ticket in all_tickets],
            },
            workload=Workload.OFFLINE,
        ):
            linked.setdefault(team_id, {})[issue_id] = list(ticket_ids)

        issue_sessions: dict[int, dict[str, int]] = {}
        baseline_sessions: dict[int, int] = {}
        linked_issues = [(team_id, issue_id) for team_id, issues in linked.items() for issue_id in issues]
        for kind, team_id, issue_id, sessions in sync_execute(
            SESSIONS_QUERY.format(issue_state_join=issue_state_join()),
            {
                "team_ids": team_ids_with_tickets,
                "window_days": WINDOW_DAYS,
                # A placeholder pair keeps the tuple list non-empty, which ClickHouse needs for IN.
                "linked_issues": linked_issues or [(0, "")],
            },
            workload=Workload.OFFLINE,
        ):
            if kind == "issue":
                issue_sessions.setdefault(team_id, {})[issue_id] = sessions
            else:
                baseline_sessions[team_id] = sessions

        noise = noise_issue_ids(
            team_ids,
            {team_id: set(issues) for team_id, issues in linked.items()},
            timezone.now() - timedelta(days=WINDOW_DAYS),
        )
        found: dict[int, list[dict[str, Any]]] = {}
        for team_id, team_tickets in tickets_by_team.items():
            baseline = per_thousand(team_tickets.total, baseline_sessions.get(team_id, 0))
            team_linked = {
                issue_id: ticket_ids
                for issue_id, ticket_ids in linked.get(team_id, {}).items()
                if issue_id not in noise.get(team_id, set())
            }
            metas[team_id]["baseline_per_1k"] = round(baseline, 2)
            metas[team_id]["tickets_with_errors"] = len({t for ids in team_linked.values() for t in ids})
            found[team_id] = find_ticket_issues(
                team_linked,
                issue_sessions.get(team_id, {}),
                {ticket.id: ticket.number for ticket in team_tickets.tickets},
                baseline,
            )

        issues = with_issue_details(team_ids, found)
        for team_id in team_ids:
            metas[team_id]["issues"] = issues[team_id]
        return metas
