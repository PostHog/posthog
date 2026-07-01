"""Server-side formula evaluation over metric query clauses.

A formula combines clause results by name — `(a - b) / a` — evaluated
point-by-point on the shared time grid. Parsing is a tiny recursive-descent
parser (numbers, clause identifiers, + - * /, unary minus, parentheses);
nothing is ever eval()'d.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_TOKEN_RE = re.compile(r"\s*(?:(?P<ident>[A-Za-z_][A-Za-z0-9_]*)|(?P<number>\d+(?:\.\d+)?)|(?P<op>[()+\-*/]))")

# (kind, value) tuples; kind is "ident" | "number" | "op"
_Token = tuple[str, str]


def _tokenize(formula: str) -> list[_Token]:
    tokens: list[_Token] = []
    position = 0
    while position < len(formula):
        match = _TOKEN_RE.match(formula, position)
        if match is None:
            remainder = formula[position:].strip()
            if not remainder:
                break
            raise ValueError(f"Unexpected character in formula: {remainder[0]!r}")
        if match.group("ident"):
            tokens.append(("ident", match.group("ident")))
        elif match.group("number"):
            tokens.append(("number", match.group("number")))
        else:
            tokens.append(("op", match.group("op")))
        position = match.end()
    return tokens


# Parsing (and later evaluation) recurse once per nesting level; cap it so
# a pathological formula raises ValueError -> 400 instead of RecursionError.
_MAX_NESTING_DEPTH = 32


class _Parser:
    """expr := term (('+'|'-') term)* ; term := factor (('*'|'/') factor)* ;
    factor := NUMBER | IDENT | '(' expr ')' | '-' factor"""

    def __init__(self, tokens: list[_Token], known_names: frozenset[str]) -> None:
        self.tokens = tokens
        self.position = 0
        self.known_names = known_names
        self.depth = 0

    def parse(self) -> _Node:
        node = self._expr()
        if self.position < len(self.tokens):
            raise ValueError(f"Unexpected token in formula: {self.tokens[self.position][1]!r}")
        return node

    def _peek(self) -> _Token | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _take(self) -> _Token:
        token = self._peek()
        if token is None:
            raise ValueError("Unexpected end of formula")
        self.position += 1
        return token

    def _expr(self) -> _Node:
        node = self._term()
        while (token := self._peek()) is not None and token[0] == "op" and token[1] in "+-":
            self._take()
            node = ("binop", token[1], node, self._term())
        return node

    def _term(self) -> _Node:
        node = self._factor()
        while (token := self._peek()) and token[0] == "op" and token[1] in "*/":
            self._take()
            node = ("binop", token[1], node, self._factor())
        return node

    def _factor(self) -> _Node:
        if self.depth >= _MAX_NESTING_DEPTH:
            raise ValueError(f"Formula nesting is too deep (maximum {_MAX_NESTING_DEPTH} levels)")
        self.depth += 1
        try:
            token = self._take()
            if token == ("op", "-"):
                return ("neg", self._factor())
            if token == ("op", "("):
                node = self._expr()
                closing = self._take()
                if closing != ("op", ")"):
                    raise ValueError("Unbalanced parentheses in formula")
                return node
            if token[0] == "number":
                return ("number", float(token[1]))
            if token[0] == "ident":
                if token[1] not in self.known_names:
                    raise ValueError(
                        f"Unknown clause {token[1]!r} in formula; available clauses: {sorted(self.known_names)}"
                    )
                return ("ident", token[1])
            raise ValueError(f"Unexpected token in formula: {token[1]!r}")
        finally:
            self.depth -= 1


# AST nodes are plain tuples: ("number", float) | ("ident", str) |
# ("neg", node) | ("binop", "+-*/", left, right)
_Node = tuple


def parse_formula(formula: str, known_names: frozenset[str]) -> _Node:
    """Parse and validate a formula; raises `ValueError` on any problem."""
    tokens = _tokenize(formula)
    if not tokens:
        raise ValueError("Formula is empty")
    return _Parser(tokens, known_names).parse()


def evaluate(node: _Node, values: Mapping[str, float]) -> float:
    """Evaluate one grid point. Division by zero yields 0.0 — charts and
    alert thresholds want a number, not a NaN hole."""
    kind = node[0]
    if kind == "number":
        return node[1]
    if kind == "ident":
        return values[node[1]]
    if kind == "neg":
        return -evaluate(node[1], values)
    operator, left_node, right_node = node[1], node[2], node[3]
    left, right = evaluate(left_node, values), evaluate(right_node, values)
    if operator == "+":
        return left + right
    if operator == "-":
        return left - right
    if operator == "*":
        return left * right
    if right == 0.0:
        return 0.0
    return left / right
