"""Batch evaluation of outcomes over ClickHouse events.

POC evaluator: one HogQL aggregate query per outcome, grouped by person,
`HAVING count() >= threshold`. Every run recomputes from the full event set —
the criterion is monotone, so re-evaluation can only confirm or add facts,
never flip one. Latching goes through `try_latch` (unique constraint +
insert-if-absent), and `$outcome_reached` is emitted only for rows this run
created, which keeps emission effectively-once across replays and crashes.
"""

from datetime import datetime

from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.capture import capture_batch_internal

from products.outcomes.backend.models import OUTCOME_REACHED_EVENT, Outcome, OutcomeLatch

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "outcomes_batch_evaluator"

# POC guardrail: cap how many subjects a single evaluation run processes.
MAX_SUBJECTS_PER_RUN = 10_000


def try_latch(
    outcome: Outcome, *, person_id: str, distinct_id: str, reached_at: datetime, event_count: int
) -> OutcomeLatch | None:
    """Insert the (outcome, person) fact if absent. Returns the row iff this call created it.

    The unique constraint makes this the sole convergence point: callers emit
    `$outcome_reached` only for rows they created, so concurrent or replayed
    evaluations cannot double-emit, and `reached_at` is immutable once written.
    """
    latch, created = OutcomeLatch.objects.get_or_create(
        outcome=outcome,
        person_id=person_id,
        defaults={
            "team_id": outcome.team_id,
            "distinct_id": distinct_id,
            "reached_at": reached_at,
            "event_count": event_count,
        },
    )
    return latch if created else None


def evaluate_outcome(outcome: Outcome) -> int:
    """Evaluate one outcome against its team's events. Returns the number of newly latched persons."""
    if outcome.target_event == OUTCOME_REACHED_EVENT:
        logger.warning("outcomes_loop_guard_skipped_evaluation", outcome_id=str(outcome.id))
        return 0

    # reached_at is the timestamp of the threshold-crossing (Nth) event, so any two
    # correct evaluators agree on it regardless of when they run.
    response = execute_hogql_query(
        """
        SELECT
            person_id,
            any(distinct_id) AS subject_distinct_id,
            count() AS event_count,
            arrayElement(arraySort(groupArray(timestamp)), {threshold}) AS reached_at
        FROM events
        WHERE event = {target_event}
        GROUP BY person_id
        HAVING count() >= {threshold}
        ORDER BY reached_at ASC
        LIMIT {limit}
        """,
        placeholders={
            "target_event": ast.Constant(value=outcome.target_event),
            "threshold": ast.Constant(value=outcome.threshold),
            "limit": ast.Constant(value=MAX_SUBJECTS_PER_RUN),
        },
        team=outcome.team,
    )
    results = response.results or []
    if len(results) >= MAX_SUBJECTS_PER_RUN:
        logger.warning(
            "outcomes_evaluation_truncated",
            outcome_id=str(outcome.id),
            team_id=outcome.team_id,
            limit=MAX_SUBJECTS_PER_RUN,
        )

    # Facts found before the first calculation are historical catch-up: mark them so
    # downstream automation can opt out of reacting to a mass backfill.
    backfilled = outcome.last_calculated_at is None

    new_latches: list[OutcomeLatch] = []
    for person_id, distinct_id, event_count, reached_at in results:
        latch = try_latch(
            outcome, person_id=person_id, distinct_id=distinct_id, reached_at=reached_at, event_count=event_count
        )
        if latch is not None:
            new_latches.append(latch)

    if new_latches:
        _emit_outcome_reached(outcome, new_latches, backfilled=backfilled)

    outcome.last_calculated_at = timezone.now()
    outcome.save(update_fields=["last_calculated_at", "updated_at"])

    logger.info(
        "outcomes_evaluation_completed",
        outcome_id=str(outcome.id),
        team_id=outcome.team_id,
        matched=len(results),
        newly_latched=len(new_latches),
    )
    return len(new_latches)


def _emit_outcome_reached(outcome: Outcome, latches: list[OutcomeLatch], *, backfilled: bool) -> None:
    """Capture `$outcome_reached` into the team's own event stream — the only integration surface.

    Emission happens strictly after latching: a capture failure delays the event but never
    loses the fact (a reconciler re-emit is deferred to post-POC).
    """
    try:
        capture_batch_internal(
            events=[
                {
                    "event": OUTCOME_REACHED_EVENT,
                    "distinct_id": latch.distinct_id,
                    "timestamp": latch.reached_at,
                    "properties": {
                        "outcome_id": str(outcome.id),
                        "outcome_name": outcome.name,
                        "target_event": outcome.target_event,
                        "threshold": outcome.threshold,
                        "event_count": latch.event_count,
                        "backfilled": backfilled,
                    },
                }
                for latch in latches
            ],
            token=outcome.team.api_token,
            event_source=EVENT_SOURCE,
        ).raise_for_status()
    except Exception:
        logger.exception(
            "outcomes_emission_failed",
            outcome_id=str(outcome.id),
            team_id=outcome.team_id,
            event_count=len(latches),
        )
