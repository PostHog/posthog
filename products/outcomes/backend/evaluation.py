"""Batch evaluation of outcomes over ClickHouse events.

The criteria kernel (`criteria.py`) is compiled into a single HogQL aggregate
per outcome definition: one pass over the team's events, grouped by person,
producing per atom the attained aggregate and the timestamp of the event that
crossed the threshold. The HAVING clause keeps only persons satisfying at
least one path; `criteria.resolve()` then folds the per-atom columns into
`reached_at`, the winning path, and the evidence payload — so query and kernel
cannot disagree on what "reached" means.

Each run recomputes from the definition's lookback window: the grammar is
monotone, so re-evaluation can only confirm or add facts, never flip one.

A run processes at most `MAX_SUBJECTS_PER_RUN` persons, so the population is
walked in person_id order across runs, with `evaluation_cursor` carrying the
high-water mark and resetting to null when a sweep runs dry. The cursor is what
guarantees forward progress: dedup is left entirely to `try_latch` (unique
constraint + insert-if-absent) rather than to an exclusion list, which cannot
both fit in a query and cover a large reached population. `$outcome_reached` is
emitted only for rows this run created, which keeps emission effectively-once
across replays and crashes.
"""

from datetime import datetime, timedelta
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
from products.outcomes.backend.models import OutcomeDefinition, OutcomeLatch

logger = structlog.get_logger(__name__)

EVENT_SOURCE = "outcomes_batch_evaluator"

# POC guardrail: cap how many subjects a single evaluation run processes. A sweep walks the
# whole matching population `MAX_SUBJECTS_PER_RUN` at a time, so this bounds the result set and
# the per-run latch writes, not how much of the population is ever reachable.
MAX_SUBJECTS_PER_RUN = 50_000


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
        # Attained is the highest time-ordered running sum, not the final total: once the
        # threshold is crossed the atom stays satisfied even if later negative values
        # (refunds) pull the total back down — this keeps sum monotone. The leading 0
        # also makes the array non-empty and floors all-negative histories at 0.
        columns = [
            f"arrayMax(arrayPushFront(arrayCumSum({values_by_ts}), 0)) AS attained_{index}",
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


def _compile_query(
    criteria: Criteria, team: Team, *, lookback_days: int, cursor: str | None
) -> tuple[str, dict[str, ast.Expr]]:
    flat = criteria.flat_atoms()
    columns: list[str] = ["person_id", "any(distinct_id) AS subject_distinct_id"]
    placeholders: dict[str, ast.Expr] = {
        "events": ast.Constant(value=sorted({atom.event for _, atom in flat})),
        "limit": ast.Constant(value=MAX_SUBJECTS_PER_RUN),
        "since": ast.Constant(value=timezone.now() - timedelta(days=lookback_days)),
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

    # The timestamp bound is what keeps the scan proportional to the window rather than to the
    # team's whole history; without it this is a full-history scan on every run.
    where = "event IN {events} AND timestamp >= {since}"
    if cursor is not None:
        where += " AND person_id > {cursor}"
        placeholders["cursor"] = ast.Constant(value=cursor)

    query = f"""
        SELECT {", ".join(columns)}
        FROM events
        WHERE {where}
        GROUP BY person_id
        HAVING {" OR ".join(path_conditions)}
        ORDER BY person_id
        LIMIT {{limit}}
    """
    return query, placeholders


def _normalize_completion(value: Any) -> datetime | None:
    # arrayElement out-of-bounds yields the epoch default; treat it as "not completed"
    # so a malformed column fails toward late, never toward a wrong fact.
    if not isinstance(value, datetime) or value.timestamp() <= 0:
        return None
    return value


def try_latch(
    definition: OutcomeDefinition, *, person_id: str, distinct_id: str, resolution: Resolution
) -> OutcomeLatch | None:
    """Insert the (definition, person) fact if absent. Returns the row iff this call created it.

    The unique constraint makes this the sole convergence point: callers emit
    `$outcome_reached` only for rows they created, so concurrent or replayed
    evaluations cannot double-emit, and `reached_at` is immutable once written.
    """
    latch, created = OutcomeLatch.objects.get_or_create(
        team_id=definition.team_id,
        definition=definition,
        person_id=person_id,
        defaults={
            "distinct_id": distinct_id,
            "reached_at": resolution.reached_at,
            "evidence": resolution.evidence,
        },
    )
    return latch if created else None


def evaluate_outcome(definition: OutcomeDefinition) -> int:
    """Evaluate one outcome definition against its team's events. Returns the number of newly latched persons."""
    try:
        criteria = parse_criteria(definition.criteria)
    except CriteriaValidationError:
        logger.exception("outcomes_invalid_criteria_skipped", outcome_id=str(definition.id), team_id=definition.team_id)
        return 0

    cursor = str(definition.evaluation_cursor) if definition.evaluation_cursor else None
    query, placeholders = _compile_query(
        criteria, definition.team, lookback_days=definition.lookback_days, cursor=cursor
    )
    response = execute_hogql_query(query, placeholders=placeholders, team=definition.team)
    results = response.results or []

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
        latch = try_latch(definition, person_id=person_id, distinct_id=distinct_id, resolution=resolution)
        if latch is not None:
            new_latches.append(latch)

    if new_latches:
        _emit_outcome_reached(definition, new_latches)

    # A short page means the sweep reached the end of the population; start the next one from
    # the beginning so persons who reach the outcome behind the cursor are still picked up.
    swept_to_end = len(results) < MAX_SUBJECTS_PER_RUN
    definition.evaluation_cursor = None if swept_to_end else results[-1][0]
    definition.last_calculated_at = timezone.now()
    definition.save(update_fields=["evaluation_cursor", "last_calculated_at", "updated_at"])

    logger.info(
        "outcomes_evaluation_completed",
        outcome_id=str(definition.id),
        team_id=definition.team_id,
        matched=len(results),
        newly_latched=len(new_latches),
        sweep_completed=swept_to_end,
    )
    return len(new_latches)


def _emit_outcome_reached(definition: OutcomeDefinition, latches: list[OutcomeLatch]) -> None:
    """Capture `$outcome_reached` into the team's own event stream — the only integration surface.

    Emission happens strictly after latching: a capture failure delays the event but never
    loses the fact (a reconciler re-emit is deferred to post-POC).

    `backfilled` is per fact, not per run: a person whose threshold-crossing event predates the
    definition reached it historically no matter which run happened to find them. Deriving it
    from the run instead marks everything after the first run as live, which is what would
    fire automations on years-old facts as a sweep works through the population.
    """
    try:
        capture_batch_internal(
            events=[
                {
                    "event": OUTCOME_REACHED_EVENT,
                    "distinct_id": latch.distinct_id,
                    "timestamp": latch.reached_at,
                    "properties": {
                        "outcome_id": str(definition.id),
                        "outcome_name": definition.name,
                        "evidence": latch.evidence,
                        "backfilled": latch.reached_at < definition.created_at,
                    },
                }
                for latch in latches
            ],
            token=definition.team.api_token,
            event_source=EVENT_SOURCE,
        ).raise_for_status()
    except Exception:
        logger.exception(
            "outcomes_emission_failed",
            outcome_id=str(definition.id),
            team_id=definition.team_id,
            event_count=len(latches),
        )
