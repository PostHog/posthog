"""Batch evaluation of outcomes over ClickHouse events.

The criteria kernel (`criteria.py`) is compiled into a single HogQL aggregate
per outcome: one pass over the team's events, grouped by person, producing per
atom the attained aggregate and the timestamp of the event that crossed the
threshold. The HAVING clause keeps only persons satisfying at least one path;
`criteria.resolve()` then folds the per-atom columns into `reached_at`, the
winning path, and the evidence payload — so query and kernel cannot disagree
on what "reached" means.

Every run recomputes from the full event set: the grammar is monotone, so
re-evaluation can only confirm or add facts, never flip one. Latching goes
through `try_latch` (unique constraint + insert-if-absent), and
`$outcome_reached` is emitted only for rows this run created, which keeps
emission effectively-once across replays and crashes.
"""

from datetime import datetime
from typing import Any

from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.api.capture import capture_batch_internal
from posthog.models.team.team import Team

from products.outcomes.backend.criteria import (
    OUTCOME_REACHED_EVENT,
    Atom,
    AtomOutcome,
    Criteria,
    CriteriaValidationError,
    Resolution,
    parse_criteria,
    resolve,
)
from products.outcomes.backend.models import Outcome, OutcomeLatch

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "outcomes_batch_evaluator"

# POC guardrail: cap how many subjects a single evaluation run processes.
MAX_SUBJECTS_PER_RUN = 10_000


def _atom_condition(atom: Atom, team: Team) -> ast.Expr:
    exprs: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=atom.event),
        )
    ]
    if atom.properties:
        exprs.append(property_to_expr(list(atom.properties), team))
    return ast.And(exprs=exprs) if len(exprs) > 1 else exprs[0]


def _aggregation_value_expr(atom: Atom) -> ast.Expr:
    prop = ast.Constant(value=atom.aggregation_property)
    if atom.aggregation == "sum":
        return parse_expr("toFloat(properties[{key}])", {"key": prop})
    return parse_expr("toString(properties[{key}])", {"key": prop})


def _atom_columns(atom: Atom, index: int) -> tuple[list[str], dict[str, ast.Expr]]:
    """SQL column fragments and placeholders computing this atom's attained aggregate and
    the timestamp of the threshold-crossing event (the atom's completion time)."""
    cond = f"{{cond_{index}}}"
    threshold = f"{{t_{index}}}"
    ts_sorted = f"arraySort(groupArrayIf(timestamp, {cond}))"

    placeholders: dict[str, ast.Expr] = {}
    if atom.aggregation == "count":
        placeholders[f"t_{index}"] = ast.Constant(value=int(atom.threshold))
        columns = [
            f"countIf({cond}) AS attained_{index}",
            # The Nth matching event is the one that crossed the threshold.
            f"arrayElement({ts_sorted}, {threshold}) AS completion_{index}",
        ]
    elif atom.aggregation == "sum":
        placeholders[f"t_{index}"] = ast.Constant(value=float(atom.threshold))
        value = f"{{val_{index}}}"
        placeholders[f"val_{index}"] = _aggregation_value_expr(atom)
        values_by_ts = f"arraySort((v, t) -> t, groupArrayIf({value}, {cond}), groupArrayIf(timestamp, {cond}))"
        columns = [
            f"sumIf({value}, {cond}) AS attained_{index}",
            # The event where the running (time-ordered) sum first reaches the threshold.
            f"arrayElement({ts_sorted}, arrayFirstIndex(x -> x >= {threshold}, arrayCumSum({values_by_ts})))"
            f" AS completion_{index}",
        ]
    else:  # distinct
        placeholders[f"t_{index}"] = ast.Constant(value=int(atom.threshold))
        value = f"{{val_{index}}}"
        placeholders[f"val_{index}"] = _aggregation_value_expr(atom)
        values_by_ts = f"arraySort((v, t) -> t, groupArrayIf({value}, {cond}), groupArrayIf(timestamp, {cond}))"
        # Positions of first occurrences in time order; the Nth one is the event that
        # brought the distinct count to the threshold.
        first_seen_positions = (
            f"arrayFilter((i, u) -> u = 1, arrayEnumerate({values_by_ts}),"
            f" arrayEnumerateUniq({values_by_ts}, {values_by_ts}))"
        )
        columns = [
            f"uniqExactIf({value}, {cond}) AS attained_{index}",
            f"arrayElement({ts_sorted}, arrayElement({first_seen_positions}, {threshold})) AS completion_{index}",
        ]
    return columns, placeholders


def _compile_query(criteria: Criteria, team: Team) -> tuple[str, dict[str, ast.Expr]]:
    flat = criteria.flat_atoms()
    columns: list[str] = ["person_id", "any(distinct_id) AS subject_distinct_id"]
    placeholders: dict[str, ast.Expr] = {
        "events": ast.Constant(value=sorted({atom.event for _, atom in flat})),
        "limit": ast.Constant(value=MAX_SUBJECTS_PER_RUN),
    }

    for index, (_, atom) in enumerate(flat):
        placeholders[f"cond_{index}"] = _atom_condition(atom, team)
        atom_columns, atom_placeholders = _atom_columns(atom, index)
        columns.extend(atom_columns)
        placeholders.update(atom_placeholders)

    path_conditions: list[str] = []
    offset = 0
    for path in criteria.paths:
        satisfied_terms = [f"toInt(attained_{offset + i} >= {{t_{offset + i}}})" for i in range(len(path.atoms))]
        path_conditions.append(f"(({' + '.join(satisfied_terms)}) >= {path.effective_min_matches})")
        offset += len(path.atoms)

    query = f"""
        SELECT {", ".join(columns)}
        FROM events
        WHERE event IN {{events}}
        GROUP BY person_id
        HAVING {" OR ".join(path_conditions)}
        LIMIT {{limit}}
    """
    return query, placeholders


def _normalize_completion(value: Any) -> datetime | None:
    # arrayElement out-of-bounds yields the epoch default; treat it as "not completed"
    # so a malformed column fails toward late, never toward a wrong fact.
    if not isinstance(value, datetime) or value.timestamp() <= 0:
        return None
    return value


def try_latch(outcome: Outcome, *, person_id: str, distinct_id: str, resolution: Resolution) -> OutcomeLatch | None:
    """Insert the (outcome, person) fact if absent. Returns the row iff this call created it.

    The unique constraint makes this the sole convergence point: callers emit
    `$outcome_reached` only for rows they created, so concurrent or replayed
    evaluations cannot double-emit, and `reached_at` is immutable once written.
    """
    latch, created = OutcomeLatch.objects.get_or_create(
        team_id=outcome.team_id,
        outcome=outcome,
        person_id=person_id,
        defaults={
            "distinct_id": distinct_id,
            "reached_at": resolution.reached_at,
            "evidence": resolution.evidence,
        },
    )
    return latch if created else None


def evaluate_outcome(outcome: Outcome) -> int:
    """Evaluate one outcome against its team's events. Returns the number of newly latched persons."""
    try:
        criteria = parse_criteria(outcome.criteria)
    except CriteriaValidationError:
        logger.exception("outcomes_invalid_criteria_skipped", outcome_id=str(outcome.id), team_id=outcome.team_id)
        return 0

    query, placeholders = _compile_query(criteria, outcome.team)
    response = execute_hogql_query(query, placeholders=placeholders, team=outcome.team)
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

    atom_count = len(criteria.flat_atoms())
    new_latches: list[OutcomeLatch] = []
    for row in results:
        person_id, distinct_id = row[0], row[1]
        atom_outcomes = [
            AtomOutcome(
                attained=float(row[2 + 2 * i] or 0),
                completion=_normalize_completion(row[3 + 2 * i]),
            )
            for i in range(atom_count)
        ]
        resolution = resolve(criteria, atom_outcomes)
        if resolution is None:
            continue
        latch = try_latch(outcome, person_id=person_id, distinct_id=distinct_id, resolution=resolution)
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
                        "evidence": latch.evidence,
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
