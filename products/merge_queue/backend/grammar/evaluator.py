"""Condition-grammar evaluator.

Evaluates a parsed `Predicate` against a PR's facts. Used by auto-enroll gating today and
by partition predicates once the router lands.

`checks-green` reads a precomputed boolean: resolving the *set* of required checks for a PR
(including the Visual Review gate) lives in the GitHub adapter, not here — the
evaluator stays a pure function of the facts it is handed.
"""

import fnmatch
from dataclasses import dataclass

from products.merge_queue.backend.grammar.parser import Atom, AtomKind, Predicate, parse


@dataclass(frozen=True)
class PRFacts:
    approved: bool
    checks_green: bool  # all required checks (incl. Visual Review) resolved green
    changed_files: frozenset[str]
    labels: frozenset[str]


def _atom_holds(atom: Atom, facts: PRFacts) -> bool:
    match atom.kind:
        case AtomKind.APPROVED:
            result = facts.approved
        case AtomKind.CHECKS_GREEN:
            result = facts.checks_green
        case AtomKind.FILES_GLOB:
            assert atom.value is not None
            result = any(fnmatch.fnmatchcase(path, atom.value) for path in facts.changed_files)
        case AtomKind.LABEL:
            result = atom.value in facts.labels
    return not result if atom.negated else result


def evaluate(predicate: Predicate | str, facts: PRFacts) -> bool:
    """True iff every atom in the conjunction holds against `facts`."""
    if isinstance(predicate, str):
        predicate = parse(predicate)
    return all(_atom_holds(atom, facts) for atom in predicate.atoms)
