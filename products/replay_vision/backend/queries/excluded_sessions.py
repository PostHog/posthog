"""Negative-filter exclusion, asked about the candidates a sweep already holds.

A scanner with a negative filter ("host is not X") must never observe a session containing a
disqualifying event, and an observation cannot be retracted. The recordings list enforces that with a
`globalNotIn` subquery that builds every blocked session across the whole lookback, then anti-joins
during selection. Correct, but it costs the same whether the tick has one candidate or none.

The sweep already knows which sessions it is about to dispatch, and that set is small: bounded by the
scanner's in-flight headroom. So it turns the in-query blocklists off, fetches candidates, and asks
the narrow question instead, which prunes on session id rather than sweeping the window. A tick with
no candidates asks nothing at all.

Nothing is cached. The check is a live query evaluated after the candidates are chosen, so it reads a
strictly more recent snapshot than the in-query form would have, and mutable inputs (cohort
membership, group and person properties) resolve at query time exactly as they do today.
"""

import structlog
from opentelemetry import trace

from posthog.schema import FilterLogicalOperator, RecordingsQuery

from posthog.models import Team
from posthog.session_recordings.queries.sub_queries.events_subquery import ReplayFiltersEventsSubQuery
from posthog.session_recordings.queries.utils import expand_test_account_filters

from products.replay_vision.backend.queries.scanner_candidate_query import CandidateSession, execute_candidate_query

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

# Bounded by the caller's candidate batch, so it only has to outlast a scan over named session ids.
_MAX_EXECUTION_SECONDS = 60


def has_negative_filters(team: Team, query: RecordingsQuery) -> bool:
    """Whether this query excludes anything, i.e. whether the sweep needs to ask at all."""
    return any(builder.negative_properties() for builder in _builders(team, query))


@tracer.start_as_current_span("excluded_session_ids")
def excluded_session_ids(*, team: Team, query: RecordingsQuery, candidates: list[CandidateSession]) -> set[str]:
    """Which of `candidates` carry an event that a negative filter excludes.

    Raises rather than returning a partial answer. The caller has already disabled the in-query
    blocklists by this point, so a swallowed failure here would dispatch the whole batch unfiltered.
    """
    session_ids = [c.session_id for c in candidates]
    if not session_ids:
        return set()

    excluded: set[str] = set()
    for builder in _builders(team, query):
        exclusion = builder.get_excluded_sessions_query(session_ids)
        if exclusion is None:
            continue
        rows = execute_candidate_query(
            exclusion,
            team=team,
            query_type="ReplayVisionExcludedSessionsQuery",
            max_execution_time_seconds=_MAX_EXECUTION_SECONDS,
        )
        excluded.update(row[0] for row in rows)
    return excluded


def _builders(team: Team, query: RecordingsQuery) -> list[ReplayFiltersEventsSubQuery]:
    """One builder per source of negative filters: the scanner's own, plus the team's test-account set.

    Test-account filters are always AND'd regardless of the scanner's operand, which is why they are
    a separate builder rather than merged into the query's property list.
    """
    builders = [ReplayFiltersEventsSubQuery(team, query)]
    if query.filter_test_accounts:
        filters = expand_test_account_filters(team)
        if filters:
            scoped = query.model_copy(deep=True)
            scoped.properties = list(filters)
            scoped.operand = FilterLogicalOperator.AND_
            scoped.events = None
            scoped.actions = None
            scoped.console_log_filters = None
            builders.append(ReplayFiltersEventsSubQuery(team, scoped))
    return builders
