"""The semantics kernel for outcome criteria.

Grammar (two levels of nesting, no more): paths are OR'd together; atoms within
a path are AND'd, optionally relaxed to M-of-N via ``min_matches``. An atom
aggregates events monotonically — ``count`` of matching events, ``sum`` of a
numeric property, or ``distinct`` values of a property — always compared with
``>= threshold``.

Monotonicity is a grammar-level invariant: as events arrive an admissible
criterion can only move toward satisfaction, never away from it. That is what
makes re-evaluation (and any future streaming evaluator) converge on identical
facts instead of flipping them, so this module rejects anything
non-monotone (avg, "at most", NOT/absence) by construction.

This module is deliberately pure — no Django, no HogQL — so the same
satisfaction/`reached_at`/evidence semantics can be compiled into multiple
execution forms without drifting. `resolve()` is the reference implementation
every evaluator's output must agree with.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

MAX_PATHS = 5
MAX_ATOMS = 10
AGGREGATIONS = ("count", "sum", "distinct")

# Loop guard: outcomes must never be defined over the event they themselves emit.
OUTCOME_REACHED_EVENT = "$outcome_reached"


class CriteriaValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Atom:
    """One monotone condition: aggregate of matching events compared with >= threshold."""

    event: str
    aggregation: str
    threshold: float
    properties: tuple[dict[str, Any], ...] = ()
    aggregation_property: str | None = None


@dataclass(frozen=True)
class Path:
    """Atoms AND'd together, optionally relaxed to at-least-M-of-N via min_matches."""

    atoms: tuple[Atom, ...]
    min_matches: int | None = None

    @property
    def effective_min_matches(self) -> int:
        return self.min_matches if self.min_matches is not None else len(self.atoms)


@dataclass(frozen=True)
class Criteria:
    paths: tuple[Path, ...]

    def flat_atoms(self) -> list[tuple[int, Atom]]:
        """Atoms in stable global order as (path_index, atom) — the order evaluators must use."""
        return [(path_index, atom) for path_index, path in enumerate(self.paths) for atom in path.atoms]


@dataclass(frozen=True)
class AtomOutcome:
    """A single atom's aggregates for one subject, as computed by an evaluator."""

    attained: float
    # Timestamp of the event that crossed the threshold; None when unsatisfied.
    completion: datetime | None


@dataclass(frozen=True)
class Resolution:
    """The fact: when the subject reached the outcome, through which path, with what evidence."""

    reached_at: datetime
    winning_path: int
    evidence: dict[str, Any]


def _parse_atom(data: Any, location: str) -> Atom:
    if not isinstance(data, dict):
        raise CriteriaValidationError(f"{location} must be an object.")

    event = data.get("event")
    if not isinstance(event, str) or not event.strip():
        raise CriteriaValidationError(f"{location} needs an event name.")
    if event == OUTCOME_REACHED_EVENT:
        raise CriteriaValidationError(
            f"Outcomes cannot be defined over {OUTCOME_REACHED_EVENT} — that would create an evaluation loop."
        )

    aggregation = data.get("aggregation", "count")
    if aggregation not in AGGREGATIONS:
        raise CriteriaValidationError(
            f"{location} has aggregation {aggregation!r}; only monotone aggregations are allowed: "
            f"{', '.join(AGGREGATIONS)}."
        )

    aggregation_property = data.get("aggregation_property") or None
    if aggregation in ("sum", "distinct"):
        if not isinstance(aggregation_property, str) or not aggregation_property.strip():
            raise CriteriaValidationError(f"{location} needs an aggregation_property for {aggregation}.")
    elif aggregation_property is not None:
        raise CriteriaValidationError(f"{location} must not set aggregation_property for count.")

    threshold = data.get("threshold", 1)
    if isinstance(threshold, bool) or not isinstance(threshold, int | float):
        raise CriteriaValidationError(f"{location} threshold must be a number.")
    if aggregation in ("count", "distinct"):
        if threshold != int(threshold) or threshold < 1:
            raise CriteriaValidationError(f"{location} threshold must be a whole number of at least 1.")
        threshold = int(threshold)
    elif threshold <= 0:
        raise CriteriaValidationError(f"{location} threshold must be greater than 0 for sum.")

    properties = data.get("properties") or []
    if not isinstance(properties, list) or not all(isinstance(p, dict) for p in properties):
        raise CriteriaValidationError(f"{location} properties must be a list of property filters.")

    return Atom(
        event=event,
        aggregation=aggregation,
        threshold=float(threshold),
        properties=tuple(properties),
        aggregation_property=aggregation_property,
    )


def parse_criteria(data: Any) -> Criteria:
    """Parse and validate a criteria dict. Raises CriteriaValidationError on any violation."""
    if not isinstance(data, dict):
        raise CriteriaValidationError("Criteria must be an object with a list of paths.")

    raw_paths = data.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        raise CriteriaValidationError("Criteria needs at least one path.")
    if len(raw_paths) > MAX_PATHS:
        raise CriteriaValidationError(f"Criteria can have at most {MAX_PATHS} paths.")

    paths: list[Path] = []
    total_atoms = 0
    for path_index, raw_path in enumerate(raw_paths):
        if not isinstance(raw_path, dict):
            raise CriteriaValidationError(f"Path {path_index + 1} must be an object.")
        raw_atoms = raw_path.get("atoms")
        if not isinstance(raw_atoms, list) or not raw_atoms:
            raise CriteriaValidationError(f"Path {path_index + 1} needs at least one condition.")
        atoms = tuple(
            _parse_atom(raw_atom, f"Path {path_index + 1}, condition {atom_index + 1}")
            for atom_index, raw_atom in enumerate(raw_atoms)
        )
        total_atoms += len(atoms)

        min_matches = raw_path.get("min_matches")
        if min_matches is not None:
            if isinstance(min_matches, bool) or not isinstance(min_matches, int):
                raise CriteriaValidationError(f"Path {path_index + 1} min_matches must be a whole number.")
            if not 1 <= min_matches <= len(atoms):
                raise CriteriaValidationError(f"Path {path_index + 1} min_matches must be between 1 and {len(atoms)}.")
        paths.append(Path(atoms=atoms, min_matches=min_matches))

    if total_atoms > MAX_ATOMS:
        raise CriteriaValidationError(f"Criteria can have at most {MAX_ATOMS} conditions in total.")

    return Criteria(paths=tuple(paths))


def resolve(criteria: Criteria, atom_outcomes: list[AtomOutcome]) -> Resolution | None:
    """Fold per-atom outcomes into the fact, or None when the outcome is not reached.

    ``atom_outcomes`` must be ordered like ``criteria.flat_atoms()``. A path completes at
    the moment its ``min_matches``-th atom completed; the outcome completes at the earliest
    path completion (`reached_at` is a function of the event set alone — invariant I1).
    An atom that reports attained >= threshold but no completion time is treated as
    unsatisfied: evaluators fail toward late, never toward wrong.
    """
    flat = criteria.flat_atoms()
    if len(atom_outcomes) != len(flat):
        raise ValueError(f"Expected {len(flat)} atom outcomes, got {len(atom_outcomes)}.")

    per_path: list[list[tuple[Atom, AtomOutcome]]] = [[] for _ in criteria.paths]
    for (path_index, atom), outcome in zip(flat, atom_outcomes):
        per_path[path_index].append((atom, outcome))

    reached_at: datetime | None = None
    winning_path: int | None = None
    evidence_paths: list[dict[str, Any]] = []

    for path_index, path in enumerate(criteria.paths):
        atom_evidence: list[dict[str, Any]] = []
        completions: list[datetime] = []
        for atom, outcome in per_path[path_index]:
            satisfied = outcome.attained >= atom.threshold and outcome.completion is not None
            if satisfied and outcome.completion is not None:
                completions.append(outcome.completion)
            atom_evidence.append(
                {
                    "event": atom.event,
                    "aggregation": atom.aggregation,
                    "aggregation_property": atom.aggregation_property,
                    "threshold": atom.threshold,
                    "attained": outcome.attained,
                    "satisfied": satisfied,
                }
            )

        path_satisfied = len(completions) >= path.effective_min_matches
        path_completion: datetime | None = None
        if path_satisfied:
            path_completion = sorted(completions)[path.effective_min_matches - 1]
            if reached_at is None or path_completion < reached_at:
                reached_at = path_completion
                winning_path = path_index

        evidence_paths.append(
            {
                "satisfied": path_satisfied,
                "min_matches": path.effective_min_matches,
                "atoms": atom_evidence,
            }
        )

    if reached_at is None or winning_path is None:
        return None

    return Resolution(
        reached_at=reached_at,
        winning_path=winning_path,
        evidence={"winning_path": winning_path, "paths": evidence_paths},
    )
