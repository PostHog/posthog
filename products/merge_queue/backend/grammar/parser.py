"""Condition-grammar parser.

One small, fixed-keyword grammar with two consumers: auto-enroll gating and partition
predicates. Deliberately not a general expression language — a conjunction of optionally
negated atoms — so predicates stay statically analyzable (the router reasons about overlap
and we never want an unbounded predicate on the hot path).

Grammar (whitespace-separated, implicit AND):

    predicate := term (WS term)*
    term      := ["!" | "not" WS] atom
    atom      := "approved"
               | "checks-green"
               | "files~=" GLOB
               | "label=" NAME
"""

from dataclasses import dataclass
from enum import StrEnum


class GrammarError(ValueError):
    """Raised when a predicate string is malformed."""


class AtomKind(StrEnum):
    APPROVED = "approved"
    CHECKS_GREEN = "checks_green"
    FILES_GLOB = "files_glob"
    LABEL = "label"


@dataclass(frozen=True)
class Atom:
    kind: AtomKind
    negated: bool = False
    value: str | None = None  # set for FILES_GLOB (the glob) and LABEL (the name)


@dataclass(frozen=True)
class Predicate:
    """A conjunction of atoms — all must hold."""

    atoms: tuple[Atom, ...]


_FILES_PREFIX = "files~="
_LABEL_PREFIX = "label="


def _parse_atom(token: str, *, negated: bool) -> Atom:
    if token == "approved":
        return Atom(AtomKind.APPROVED, negated)
    if token == "checks-green":
        return Atom(AtomKind.CHECKS_GREEN, negated)
    if token.startswith(_FILES_PREFIX):
        value = token[len(_FILES_PREFIX) :]
        if not value:
            raise GrammarError("files~= requires a glob")
        return Atom(AtomKind.FILES_GLOB, negated, value)
    if token.startswith(_LABEL_PREFIX):
        value = token[len(_LABEL_PREFIX) :]
        if not value:
            raise GrammarError("label= requires a name")
        return Atom(AtomKind.LABEL, negated, value)
    raise GrammarError(f"unknown term: {token!r}")


def parse(source: str) -> Predicate:
    """Parse a predicate string into an AST. Raises `GrammarError` on malformed input."""
    tokens = source.split()
    if not tokens:
        raise GrammarError("empty predicate")

    atoms: list[Atom] = []
    negate_next = False
    for token in tokens:
        if token.lower() == "not":
            if negate_next:
                raise GrammarError("double negation")
            negate_next = True
            continue
        negated = negate_next
        if token.startswith("!"):
            negated = not negated
            token = token[1:]
            if not token:
                raise GrammarError("dangling negation")
        atoms.append(_parse_atom(token, negated=negated))
        negate_next = False

    if negate_next:
        raise GrammarError("dangling 'not'")
    return Predicate(tuple(atoms))
