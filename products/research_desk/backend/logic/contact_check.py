from datetime import datetime, timedelta

from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team

from ..facade import contracts
from ..facade.enums import SourceKind, TouchChannel
from ..models import ResearchSource
from .emails import normalize_domain, normalize_emails
from .sessions import sessions_with_contact

WORKFLOW_EMAIL_SENT_EVENT = "$workflows_email_sent"
SURVEY_TOUCH_EVENTS = ("survey shown", "survey sent")
MAX_EVENT_TOUCHES = 200
MAX_COHORT_SOURCES = 25
MAX_COHORT_MATCHES = 50

EVENT_TOUCHES_QUERY = """
SELECT
    event,
    toString(properties.$workflow_id),
    toString(properties.$survey_id),
    lower(toString(coalesce(properties.$email_to, person.properties.email))),
    timestamp
FROM events
WHERE timestamp >= {since} AND {contact_match} AND {source_match}
ORDER BY timestamp DESC
LIMIT {limit}
"""

COHORT_TOUCHES_QUERY = """
SELECT DISTINCT lower(toString(properties.email))
FROM persons
WHERE id IN COHORT {cohort_id} AND {contact_match}
LIMIT {limit}
"""


def _contact_match(fields: list[list[str]], emails: list[str], domain: str | None) -> ast.Expr:
    clauses: list[ast.Expr] = []
    for chain in fields:
        value = ast.Call(name="lower", args=[ast.Call(name="toString", args=[ast.Field(chain=list(chain))])])
        if emails:
            clauses.append(
                ast.CompareOperation(op=ast.CompareOperationOp.In, left=value, right=ast.Constant(value=emails))
            )
        if domain:
            clauses.append(ast.Call(name="endsWith", args=[value, ast.Constant(value=f"@{domain}")]))
    return ast.Or(exprs=clauses)


def _source_match(sources: list[ResearchSource]) -> ast.Expr | None:
    workflow_ids = [s.external_id for s in sources if s.kind == SourceKind.WORKFLOW]
    survey_ids = [s.external_id for s in sources if s.kind == SourceKind.SURVEY]
    event_names = [s.external_id for s in sources if s.kind == SourceKind.EVENT]

    clauses: list[ast.Expr] = []
    if workflow_ids:
        clauses.append(
            parse_expr(
                "event = {event} AND toString(properties.$workflow_id) IN {ids}",
                placeholders={
                    "event": ast.Constant(value=WORKFLOW_EMAIL_SENT_EVENT),
                    "ids": ast.Constant(value=workflow_ids),
                },
            )
        )
    if survey_ids:
        clauses.append(
            parse_expr(
                "event IN {events} AND toString(properties.$survey_id) IN {ids}",
                placeholders={
                    "events": ast.Constant(value=list(SURVEY_TOUCH_EVENTS)),
                    "ids": ast.Constant(value=survey_ids),
                },
            )
        )
    if event_names:
        clauses.append(parse_expr("event IN {events}", placeholders={"events": ast.Constant(value=event_names)}))
    return ast.Or(exprs=clauses) if clauses else None


def _event_touches(
    team: Team, sources: list[ResearchSource], emails: list[str], domain: str | None, since: datetime
) -> list[contracts.ResearchTouch]:
    source_match = _source_match(sources)
    if source_match is None:
        return []

    response = execute_hogql_query(
        EVENT_TOUCHES_QUERY,
        team=team,
        query_type="research_desk_contact_check_events",
        placeholders={
            "since": ast.Constant(value=since),
            "contact_match": _contact_match(
                [["properties", "$email_to"], ["person", "properties", "email"]], emails, domain
            ),
            "source_match": source_match,
            "limit": ast.Constant(value=MAX_EVENT_TOUCHES),
        },
    )

    by_workflow = {s.external_id: s for s in sources if s.kind == SourceKind.WORKFLOW}
    by_survey = {s.external_id: s for s in sources if s.kind == SourceKind.SURVEY}
    by_event = {s.external_id: s for s in sources if s.kind == SourceKind.EVENT}

    touches: list[contracts.ResearchTouch] = []
    for event, workflow_id, survey_id, contact, timestamp in response.results or []:
        if event == WORKFLOW_EMAIL_SENT_EVENT and workflow_id in by_workflow:
            source, channel = by_workflow[workflow_id], TouchChannel.EMAIL
        elif event in SURVEY_TOUCH_EVENTS and survey_id in by_survey:
            source, channel = by_survey[survey_id], TouchChannel.SURVEY
        elif event in by_event:
            source, channel = by_event[event], TouchChannel.EVENT
        else:
            continue
        touches.append(
            contracts.ResearchTouch(
                channel=channel,
                contact=contact,
                source_label=source.label,
                owner_email=source.owner_email,
                occurred_at=timestamp,
                source_id=source.id,
            )
        )
    return touches


def _cohort_touches(
    team: Team, sources: list[ResearchSource], emails: list[str], domain: str | None
) -> list[contracts.ResearchTouch]:
    touches: list[contracts.ResearchTouch] = []
    cohorts = [s for s in sources if s.kind == SourceKind.COHORT and s.external_id.isdigit()]
    for source in cohorts[:MAX_COHORT_SOURCES]:
        response = execute_hogql_query(
            COHORT_TOUCHES_QUERY,
            team=team,
            query_type="research_desk_contact_check_cohort",
            placeholders={
                "cohort_id": ast.Constant(value=int(source.external_id)),
                "contact_match": _contact_match([["properties", "email"]], emails, domain),
                "limit": ast.Constant(value=MAX_COHORT_MATCHES),
            },
        )
        touches.extend(
            contracts.ResearchTouch(
                channel=TouchChannel.COHORT,
                contact=contact,
                source_label=source.label,
                owner_email=source.owner_email,
                occurred_at=None,
                source_id=source.id,
            )
            for (contact,) in response.results or []
        )
    return touches


def _session_touches(emails: list[str], domain: str | None, since: datetime) -> list[contracts.ResearchTouch]:
    touches: list[contracts.ResearchTouch] = []
    for session in sessions_with_contact(emails=emails, domain=domain, since=since):
        contacts = [e for e in session.external_emails if e in emails or (domain and e.endswith(f"@{domain}"))]
        touches.extend(
            contracts.ResearchTouch(
                channel=TouchChannel.SESSION,
                contact=contact,
                source_label=session.title,
                owner_email=session.organizer_email,
                occurred_at=session.start_time,
                session_id=session.id,
            )
            for contact in contacts
        )
    return touches


def check_contact(data: contracts.ContactCheckInput) -> contracts.ContactCheckResult:
    emails = normalize_emails(data.emails)
    domain = normalize_domain(data.domain) if data.domain else None
    now = timezone.now()
    since = now - timedelta(days=data.lookback_days)

    touches: list[contracts.ResearchTouch] = []
    if emails or domain:
        team = Team.objects.get(id=data.team_id)
        sources = list(ResearchSource.objects.filter(active=True))
        touches = [
            *_event_touches(team, sources, emails, domain, since),
            *_cohort_touches(team, sources, emails, domain),
            *_session_touches(emails, domain, since),
        ]

    timed = [t.occurred_at for t in touches if t.occurred_at is not None]
    last_touch_at = max(timed) if timed else None
    warn_since = now - timedelta(days=data.warn_within_days)
    # Cohort membership has no date, so a match in an active "already contacted" cohort warns too.
    recently_contacted = any(t.occurred_at is None or t.occurred_at >= warn_since for t in touches)

    touches.sort(key=lambda t: t.occurred_at or datetime.min.replace(tzinfo=now.tzinfo), reverse=True)
    return contracts.ContactCheckResult(
        emails=emails,
        domain=domain,
        touches=touches,
        last_touch_at=last_touch_at,
        recently_contacted=recently_contacted,
        warn_within_days=data.warn_within_days,
        lookback_days=data.lookback_days,
    )
