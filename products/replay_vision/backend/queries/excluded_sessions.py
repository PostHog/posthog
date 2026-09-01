"""Negative-filter exclusion, asked about the candidates a sweep already holds.

A scanner with a negative filter ("host is not X") must never observe a session containing a
disqualifying event, and an observation cannot be retracted. The recordings list enforces that with a
`globalNotIn` subquery that builds every blocked session across the whole lookback, then anti-joins
during selection. Correct, but it costs the same whether the tick has one candidate or none, and most
ticks have none.

The sweep already knows which sessions it is about to dispatch, and that set is small: bounded by the
scanner's in-flight headroom. So it turns the in-query blocklists off, fetches candidates, and asks
the narrow question instead. A tick with no candidates asks nothing at all.

The queries come from the candidate query itself rather than being rebuilt here, so they inherit the
same window and the same preprocessed filters the fetch used. Rebuilding them from the scanner's
stored query is how the two drift: that query carries no dates, so it would scan a window anchored to
now while the fetch is anchored to the watermark.

Nothing is cached. The check is a live query evaluated after the candidates are chosen, so it reads a
strictly more recent snapshot than the in-query form would have, and mutable inputs (cohort
membership, group and person properties) resolve at query time exactly as they do today.
"""

import time

from opentelemetry import trace

from posthog.models import Team

from products.replay_vision.backend.queries.scanner_candidate_query import (
    CandidateSession,
    ScannerCandidateQuery,
    WindowedCandidateQuery,
    execute_candidate_query,
)

# Both fetch candidates with the in-query blocklists off, so both owe the caller this question.
CandidateQuery = ScannerCandidateQuery | WindowedCandidateQuery

tracer = trace.get_tracer(__name__)

# Bounded by the caller's candidate batch, so it only has to outlast a scan over named session ids.
_MAX_EXECUTION_SECONDS = 60
# Overrunning the activity is worse than a slow scan: the attempt is killed after the candidates were
# found, so the tick retries from the same watermark and never dispatches. Leave room for the caller
# to finish up.
_ACTIVITY_RESERVE_SECONDS = 15
# Session ids are inlined as constants and ClickHouse caps a statement at 1 MiB, so a saturated batch
# could build a query the server rejects. That would fail the tick forever rather than once, since the
# next tick refetches the same rows.
_MAX_IDS_PER_QUERY = 1_000


@tracer.start_as_current_span("excluded_session_ids")
def excluded_session_ids(
    *,
    team: Team,
    candidate_query: CandidateQuery,
    candidates: list[CandidateSession],
    # Tags these reads in `system.query_log`. Required, because the sweep and a backfill both exclude
    # against the same scanner id, and the read meter throttles each path on what it is charged.
    query_type: str,
    scanner_id: str | None = None,
    seconds_remaining: float | None = None,
) -> set[str]:
    """Which of `candidates` carry an event that a negative filter excludes.

    Empty when the query excludes nothing, so the caller can run this unconditionally.

    Raises rather than returning a partial answer. The in-query blocklists are off by this point, so
    a swallowed failure would dispatch the whole batch unfiltered.
    """
    session_ids = [c.session_id for c in candidates]
    if not session_ids:
        return set()

    budget = _MAX_EXECUTION_SECONDS
    if seconds_remaining is not None:
        budget = min(budget, max(1, int(seconds_remaining - _ACTIVITY_RESERVE_SECONDS)))

    excluded: set[str] = set()
    deadline = time.monotonic() + budget
    for start in range(0, len(session_ids), _MAX_IDS_PER_QUERY):
        chunk = session_ids[start : start + _MAX_IDS_PER_QUERY]
        for exclusion in candidate_query.excluded_sessions_queries(chunk):
            rows = execute_candidate_query(
                exclusion,
                team=team,
                query_type=query_type,
                max_execution_time_seconds=max(1, int(deadline - time.monotonic())),
                # Metered against the scanner's read budget like its candidate query.
                scanner_id=scanner_id,
            )
            excluded.update(row[0] for row in rows)
    return excluded
