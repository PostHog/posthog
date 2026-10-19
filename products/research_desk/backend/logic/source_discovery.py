import re
from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.cohorts.backend.facade import api as cohorts_api

from ..facade.enums import SourceKind, SourceOrigin
from ..models import ResearchSource

DISCOVERY_WINDOW = timedelta(days=30)
KNOWN_RESEARCH_EVENTS = ("mcp interview invitation sent",)
RECRUITING_TEXT_PATTERN = re.compile(
    r"\b(interviews?|user research|quick chat|chat about|feedback call|feedback session|talk to (?:us|you))\b",
    re.IGNORECASE,
)
CONTACTED_COHORT_PATTERN = re.compile(
    r"\b(interviewed|interviews?|already contacted|already emailed|reached out|outreach)\b", re.IGNORECASE
)

WORKFLOW_SUBJECTS_QUERY = """
SELECT toString(properties.$workflow_id) AS workflow_id, any(toString(properties.$email_subject))
FROM events
WHERE event = '$workflows_email_sent' AND timestamp >= {since} AND workflow_id != ''
GROUP BY workflow_id
LIMIT 1000
"""

SURVEY_NAMES_QUERY = """
SELECT toString(properties.$survey_id) AS survey_id, any(toString(properties.$survey_name))
FROM events
WHERE event = 'survey shown' AND timestamp >= {since} AND survey_id != ''
GROUP BY survey_id
LIMIT 1000
"""

EVENTS_SEEN_QUERY = """
SELECT DISTINCT event FROM events WHERE event IN {events} AND timestamp >= {since}
"""


@frozen
class DiscoveredSource:
    kind: SourceKind
    external_id: str
    label: str


def looks_like_recruiting(text: str) -> bool:
    return bool(RECRUITING_TEXT_PATTERN.search(text))


def looks_like_contacted_cohort(name: str) -> bool:
    return bool(CONTACTED_COHORT_PATTERN.search(name))


def _rows(team: Team, query: str, query_type: str, placeholders: dict[str, ast.Expr]) -> list[tuple]:
    return list(execute_hogql_query(query, team=team, query_type=query_type, placeholders=placeholders).results or [])


def find_candidate_sources(team: Team, *, now: datetime) -> list[DiscoveredSource]:
    since: dict[str, ast.Expr] = {"since": ast.Constant(value=now - DISCOVERY_WINDOW)}
    candidates: list[DiscoveredSource] = []
    for workflow_id, subject in _rows(team, WORKFLOW_SUBJECTS_QUERY, "research_desk_discover_workflows", since):
        if looks_like_recruiting(subject or ""):
            candidates.append(DiscoveredSource(kind=SourceKind.WORKFLOW, external_id=workflow_id, label=subject))
    for survey_id, name in _rows(team, SURVEY_NAMES_QUERY, "research_desk_discover_surveys", since):
        if looks_like_recruiting(name or ""):
            candidates.append(DiscoveredSource(kind=SourceKind.SURVEY, external_id=survey_id, label=name))
    for cohort_id, name in cohorts_api.list_cohort_names(team_id=team.id).items():
        if looks_like_contacted_cohort(name or ""):
            candidates.append(DiscoveredSource(kind=SourceKind.COHORT, external_id=str(cohort_id), label=name))
    events_placeholders: dict[str, ast.Expr] = {**since, "events": ast.Constant(value=list(KNOWN_RESEARCH_EVENTS))}
    for (event,) in _rows(team, EVENTS_SEEN_QUERY, "research_desk_discover_events", events_placeholders):
        candidates.append(DiscoveredSource(kind=SourceKind.EVENT, external_id=event, label=event))
    return candidates


def register_discovered_sources(team_id: int, *, now: datetime) -> list[ResearchSource]:
    """Register recruiting sources nobody has registered yet.

    Sources someone deactivated stay known, so a rejected guess is never re-added.
    """
    team = Team.objects.get(id=team_id)
    known = set(ResearchSource.objects.values_list("kind", "external_id"))
    created: list[ResearchSource] = []
    for candidate in find_candidate_sources(team, now=now):
        if (candidate.kind, candidate.external_id) in known:
            continue
        known.add((candidate.kind, candidate.external_id))
        created.append(
            ResearchSource.objects.create(
                team_id=team_id,
                kind=candidate.kind,
                external_id=candidate.external_id,
                label=candidate.label[:255],
                origin=SourceOrigin.SCOUT,
            )
        )
    return created
