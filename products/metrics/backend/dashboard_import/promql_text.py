"""Small PromQL text tools for the dashboard import.

This is not a full parser. It knows tokens, strings, selectors, ranges and label lists. That is enough to
find the metric names in an expression and to edit Grafana range variables without changing anything else.
"""

from __future__ import annotations

import re
from typing import Literal

from posthog.dataclasses import frozen

from products.metrics.backend.promql import CLAUSE_LABEL

TokenKind = Literal["space", "string", "number", "ident", "variable", "punct"]

_TOKEN_RE = re.compile(
    r"""
    (?P<space>\s+|\#[^\n]*)
  | (?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`[^`]*`)
  | (?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?:[a-zA-Z]+\d*)*)
  | (?P<ident>[a-zA-Z_:][a-zA-Z0-9_:]*)
  | (?P<variable>\$\{[^}]*\}|\$[a-zA-Z_][a-zA-Z0-9_]*)
  | (?P<punct>=~|!~|!=|==|>=|<=|.)
    """,
    re.VERBOSE | re.DOTALL,
)

AGGREGATORS = frozenset(
    {
        "sum",
        "avg",
        "count",
        "min",
        "max",
        "stddev",
        "stdvar",
        "topk",
        "bottomk",
        "quantile",
        "count_values",
        "group",
        "limitk",
        "limit_ratio",
    }
)
GROUPING_KEYWORDS = frozenset({"by", "without", "on", "ignoring", "group_left", "group_right"})
KEYWORDS = GROUPING_KEYWORDS | {"bool", "and", "or", "unless", "offset", "atan2", "inf", "nan"}

# Grafana fills these per panel. PostHog runs a range-less rate or increase over the query step,
# which is what `$__rate_interval` and `$__interval` stand for.
_STEP_RANGE_VARIABLE = re.compile(r"^\$\{?__(rate_interval|interval|auto)\}?$")
_DASHBOARD_RANGE_VARIABLE = re.compile(r"^\$\{?__range\}?$")

_LOGQL_PIPELINE = re.compile(
    r"\}\s*(?:\|=|!=|\|~|!~|\|\s*(?:json|logfmt|pattern|regexp|unpack|line_format|label_format|unwrap|drop|keep|decolorize)\b)"
)


@frozen
class Token:
    kind: TokenKind
    text: str
    start: int
    end: int


@frozen
class RangeRewrite:
    expr: str
    # True when a `$__range` window became the query step, which changes what the panel shows.
    changed_meaning: bool


def tokenize(expr: str) -> list[Token]:
    tokens: list[Token] = []
    for match in _TOKEN_RE.finditer(expr):
        kind = match.lastgroup
        assert kind is not None
        tokens.append(Token(kind=kind, text=match.group(), start=match.start(), end=match.end()))  # type: ignore[arg-type]
    return tokens


def _significant(tokens: list[Token]) -> list[Token]:
    return [token for token in tokens if token.kind != "space"]


def _closing_index(tokens: list[Token], open_index: int, opener: str, closer: str) -> int:
    depth = 0
    for index in range(open_index, len(tokens)):
        token = tokens[index]
        if token.kind != "punct":
            continue
        if token.text == opener:
            depth += 1
        elif token.text == closer:
            depth -= 1
            if depth == 0:
                return index
    return len(tokens) - 1


def unquote(literal: str) -> str:
    if literal.startswith("`"):
        return literal[1:-1]
    body = literal[1:-1]
    return re.sub(r"\\(.)", r"\1", body)


def _split_elements(tokens: list[Token]) -> list[list[Token]]:
    elements: list[list[Token]] = [[]]
    for token in tokens:
        if token.kind == "punct" and token.text == ",":
            elements.append([])
        else:
            elements[-1].append(token)
    return [element for element in elements if element]


def _selector_metric_name(element: list[Token]) -> str | None:
    # A quoted name on its own is the UTF-8 selector form for a dotted OTel name: {"http.server.duration"}.
    if len(element) == 1 and element[0].kind == "string":
        return unquote(element[0].text)
    if (
        len(element) == 3
        and element[0].kind in ("ident", "string")
        and element[1].text == "="
        and element[2].kind == "string"
    ):
        label = element[0].text if element[0].kind == "ident" else unquote(element[0].text)
        if label == "__name__":
            return unquote(element[2].text)
    return None


def metric_names(expr: str) -> list[str]:
    """The metric names an expression selects, in order, without duplicates."""
    tokens = _significant(tokenize(expr))
    names: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if token.kind == "punct" and token.text == "[":
            index = _closing_index(tokens, index, "[", "]") + 1
            continue
        if token.kind == "punct" and token.text == "{":
            end = _closing_index(tokens, index, "{", "}")
            for element in _split_elements(tokens[index + 1 : end]):
                name = _selector_metric_name(element)
                if name:
                    names.append(name)
            index = end + 1
            continue
        if token.kind == "ident":
            lowered = token.text.lower()
            calls = following is not None and following.kind == "punct" and following.text == "("
            if lowered in GROUPING_KEYWORDS and calls:
                index = _closing_index(tokens, index + 1, "(", ")") + 1
                continue
            if not calls and lowered not in AGGREGATORS and lowered not in KEYWORDS:
                names.append(token.text)
        index += 1
    return list(dict.fromkeys(names))


def strip_grafana_ranges(expr: str) -> RangeRewrite:
    """Remove `[$__rate_interval]`, `[$__interval]` and `[$__range]` windows from range functions."""
    tokens = tokenize(expr)
    removals: list[tuple[int, int]] = []
    changed_meaning = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "punct" and token.text == "[":
            end = _closing_index(tokens, index, "[", "]")
            inner = expr[token.end : tokens[end].start].strip()
            if _STEP_RANGE_VARIABLE.match(inner):
                removals.append((token.start, tokens[end].end))
            elif _DASHBOARD_RANGE_VARIABLE.match(inner):
                removals.append((token.start, tokens[end].end))
                changed_meaning = True
            index = end + 1
            continue
        index += 1
    rewritten = expr
    for start, end in reversed(removals):
        rewritten = rewritten[:start] + rewritten[end:]
    return RangeRewrite(expr=rewritten, changed_meaning=changed_meaning)


def drop_match_all_matchers(expr: str) -> str:
    """Remove `label=~".*"` matchers, which Grafana writes for a variable set to All."""
    tokens = tokenize(expr)
    edits: list[tuple[int, int, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "punct" and token.text == "{":
            end = _closing_index(tokens, index, "{", "}")
            elements = _split_elements(_significant(tokens[index + 1 : end]))
            kept = [element for element in elements if not _matches_everything(element)]
            if len(kept) != len(elements):
                inner = ", ".join(expr[element[0].start : element[-1].end] for element in kept)
                previous = _previous_significant(tokens, index)
                if not inner and previous is not None and previous.kind == "ident":
                    edits.append((token.start, tokens[end].end, ""))
                else:
                    edits.append((token.end, tokens[end].start, inner))
            index = end + 1
            continue
        index += 1
    rewritten = expr
    for start, end, replacement in reversed(edits):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    return rewritten


def _previous_significant(tokens: list[Token], index: int) -> Token | None:
    for previous in reversed(tokens[:index]):
        if previous.kind != "space":
            return previous
    return None


def _matches_everything(element: list[Token]) -> bool:
    return (
        len(element) == 3
        and element[1].text == "=~"
        and element[2].kind == "string"
        and unquote(element[2].text) in (".*", "^.*$")
    )


def combine_targets(targets: list[tuple[str, str]]) -> str:
    """Join several query targets into one expression, keeping their series apart with the clause label.

    It uses the same convention as the PromQL editor, so each series shows the target's ref id.
    """
    if len(targets) == 1:
        return targets[0][1]
    labelled = [f'label_replace({expr}, "{CLAUSE_LABEL}", "{ref_id}", "", "")' for ref_id, expr in targets]
    return " or ".join(labelled)


def looks_like_logql(expr: str) -> bool:
    return bool(_LOGQL_PIPELINE.search(expr))
