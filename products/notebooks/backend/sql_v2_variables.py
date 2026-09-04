"""Notebook-level variables: bind their values into a cell's code at dispatch.

A notebook declares variables in a `<Variables>` markdown block. A SQL cell reads one as a
bare ``{name}`` placeholder; a Python cell reads it as a plain global (bound in the kernel,
see `sandbox/kernel/bootstrap.py`, not here).

Substitution happens once at dispatch, like reference inlining, so the run stores a
self-contained query and paging re-queries it without re-resolving anything.

No lane ever renders a value as SQL text. Escaping rules differ by engine and by server
setting, and a hand-rolled quote is one dialect quirk away from an injection, so each lane
passes the value as data instead:

* the **hogql** lane parses the query and swaps each placeholder for an ``ast.Constant``;
* the **duckdb** lane rewrites each ``{name}`` to DuckDB's own ``$name`` parameter and hands
  the values to the driver, which binds them (`_run_duckdb_node` in the kernel);
* a **raw connection** query refuses variables outright — it is the target engine's dialect,
  and the direct-query path carries no parameter binding yet.
"""

import re
from collections.abc import Iterator
from datetime import date, datetime
from difflib import get_close_matches
from typing import Any
from zoneinfo import ZoneInfo

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_prepared_ast
from posthog.hogql.variables import is_relative_date_value
from posthog.hogql.visitor import CloningVisitor

from posthog.dataclasses import frozen
from posthog.utils import relative_date_parse

# HogQL injects its own `{filters}` placeholder into notebook queries, so a variable could never
# take that name. Left untouched here rather than reported as undeclared.
RESERVED_VARIABLE_NAMES = frozenset({"filters"})

NotebookVariableValue = str | int | float | bool | datetime | date | None


class NotebookVariableError(Exception):
    """A cell reads a `{name}` that the notebook does not declare. User-facing."""


@frozen
class NotebookVariable:
    """One declared variable, with its value already coerced to a Python scalar."""

    name: str
    value: NotebookVariableValue


# Bare `{name}`; a dotted chain (`{variables.x}`, `{filters.y}`) is somebody else's placeholder.
_BARE_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# String literals and comments, blanked before the textual scan so a `'{country}'` inside a
# literal is neither substituted nor reported as undeclared. Mirrors the routing scan in
# sql_v2_references.
_SQL_LITERALS_AND_COMMENTS = re.compile(r"'(?:[^'\\]|\\.|'')*'|--[^\n]*|/\*.*?\*/", re.DOTALL)


def _undeclared_error(name: str, declared: list[str]) -> NotebookVariableError:
    if not declared:
        return NotebookVariableError(
            f"'{{{name}}}' is not a notebook variable. Add a Variables block to declare {name}."
        )
    suggestions = get_close_matches(name, declared, n=3, cutoff=0.6)
    if suggestions:
        return NotebookVariableError(
            f"'{{{name}}}' is not a notebook variable. Did you mean: {', '.join(suggestions)}?"
        )
    return NotebookVariableError(
        f"'{{{name}}}' is not a notebook variable. This notebook declares: {', '.join(sorted(declared))}."
    )


class _ReplaceNotebookVariables(CloningVisitor):
    """Swap each `{name}` placeholder for the declared variable's value as a constant."""

    def __init__(self, values: dict[str, NotebookVariableValue]) -> None:
        super().__init__()
        self.values = values
        self.replaced: set[str] = set()

    def visit_placeholder(self, node: ast.Placeholder) -> ast.Expr:
        chain = node.chain
        # Only a bare single-segment placeholder is a notebook variable. Anything else —
        # `{filters}`, a dotted chain, an expression placeholder — belongs to another
        # resolver and must reach it untouched.
        if not chain or len(chain) != 1 or not isinstance(chain[0], str):
            return super().visit_placeholder(node)

        name = chain[0]
        if name in RESERVED_VARIABLE_NAMES:
            return super().visit_placeholder(node)
        if name not in self.values:
            raise _undeclared_error(name, list(self.values))

        self.replaced.add(name)
        return ast.Constant(value=self.values[name], start=node.start, end=node.end)


def substitute_hogql_variables(code: str, variables: list[NotebookVariable]) -> str:
    """Bind notebook variables into a HogQL query, via the AST.

    Returns `code` untouched when it reads no `{name}` placeholder, so a query without
    variables is byte-for-byte what the user wrote. Raises NotebookVariableError when the
    query reads a name the notebook does not declare, and lets the parser's own error
    surface for a malformed query.
    """
    if not _BARE_PLACEHOLDER.search(code):
        return code

    values = {variable.name: variable.value for variable in variables}
    query = parse_select(code)
    visitor = _ReplaceNotebookVariables(values)
    substituted = visitor.visit(query)
    if not visitor.replaced:
        # Only `{filters}` (or another resolver's placeholder) was present — nothing of ours
        # changed, so don't reprint and reformat the user's query for no reason.
        return code
    return print_prepared_ast(substituted, context=HogQLContext(team_id=None), dialect="hogql")


_TAG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _skip_delimited(code: str, start: int, quote: str, backslash_escapes: bool) -> int:
    """Index just past the `quote`-delimited run beginning at `start`.

    Doubling the quote escapes it. An unterminated run reaches the end of the input, which is
    what a lexer does with it — the query is malformed either way, and treating the remainder
    as literal keeps a value out of it.
    """
    index = start + 1
    length = len(code)
    while index < length:
        char = code[index]
        if backslash_escapes and char == "\\":
            index += 2
            continue
        if char == quote:
            if index + 1 < length and code[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return length


def _skip_dollar_quoted(code: str, start: int) -> int | None:
    """Index just past the dollar-quoted run at `start`, or None if one does not begin there.

    `$tag$…$tag$` and `$$…$$` make every character between the tags literal, including a
    quote. A bare `$name` with no closing `$` is a parameter, not an opener.
    """
    index = start + 1
    length = len(code)
    while index < length and code[index] in _TAG_CHARS:
        index += 1
    if index >= length or code[index] != "$":
        return None
    tag = code[start : index + 1]
    # A tag cannot start with a digit, so `$1$` is two parameters rather than an opener.
    if len(tag) > 2 and tag[1].isdigit():
        return None
    close = code.find(tag, index + 1)
    # Unterminated: the rest of the input is inside the literal. Returning the end also keeps
    # this scan linear — a query full of unmatched openers can never re-scan the tail per tag.
    return length if close == -1 else close + len(tag)


def _executable_placeholders(code: str) -> Iterator[re.Match[str]]:
    """Yield each `{name}` that sits in executable SQL, skipping literals and comments.

    Hand-rolled rather than one regex: matching `$tag$…$tag$` with a backreference makes the
    engine rescan the tail once per unmatched opener, which is quadratic in the input and
    reachable from a single request. Here every character is visited a bounded number of
    times — each skip either jumps past a closed region or runs to the end.
    """
    index = 0
    length = len(code)
    while index < length:
        char = code[index]
        if char == "'" or char == '"':
            index = _skip_delimited(code, index, char, backslash_escapes=False)
        elif char in "eE" and index + 1 < length and code[index + 1] == "'":
            # E'…' takes backslash escapes, so a `\'` inside it does not close the string.
            index = _skip_delimited(code, index + 1, "'", backslash_escapes=True)
        elif char == "$":
            region_end = _skip_dollar_quoted(code, index)
            index = index + 1 if region_end is None else region_end
        elif code.startswith("--", index):
            newline = code.find("\n", index)
            index = length if newline == -1 else newline + 1
        elif code.startswith("/*", index):
            closing = code.find("*/", index + 2)
            index = length if closing == -1 else closing + 2
        elif char == "{":
            placeholder = _BARE_PLACEHOLDER.match(code, index)
            if placeholder is None:
                index += 1
            else:
                yield placeholder
                index = placeholder.end()
        else:
            index += 1


def substitute_duckdb_variables(
    code: str, variables: list[NotebookVariable]
) -> tuple[str, dict[str, NotebookVariableValue]]:
    """Rewrite each `{name}` to DuckDB's `$name` parameter; return the code and the values to bind.

    Nothing is escaped, so a value can never become SQL — DuckDB binds it through the driver
    (see `_run_duckdb_node`). Only placeholders in executable positions are rewritten: a
    `{name}` inside a string, a quoted identifier, a dollar-quoted block, or a comment is
    left exactly as written.

    Raises NotebookVariableError when an executable `{name}` is not a declared variable.
    """
    if not _BARE_PLACEHOLDER.search(code):
        return code, {}

    values = {variable.name: variable.value for variable in variables}
    used: dict[str, NotebookVariableValue] = {}
    pieces: list[str] = []
    cursor = 0

    for match in _executable_placeholders(code):
        name = match.group(1)
        if name in RESERVED_VARIABLE_NAMES:
            continue
        if name not in values:
            raise _undeclared_error(name, list(values))
        pieces.append(code[cursor : match.start()])
        pieces.append(f"${name}")
        used[name] = values[name]
        cursor = match.end()
    pieces.append(code[cursor:])
    return "".join(pieces), used


def reject_variables_in_raw_query(code: str, variables: list[NotebookVariable]) -> None:
    """Raise if a raw-connection query reads a notebook variable.

    A raw query is the target engine's own dialect, and escaping rules differ by engine and by
    server setting — MySQL treats a backslash as an escape unless NO_BACKSLASH_ESCAPES is set,
    so a shared quote-doubling helper is not safe there. Binding these values needs the driver's
    own parameter binding, which the direct-query path does not carry yet, so the run is refused
    rather than run with a hand-rolled escape.

    Only declared names are rejected: raw SQL may use braces for its own purposes, and a query
    that reads no variable is left completely alone.
    """
    if not _BARE_PLACEHOLDER.search(code):
        return

    declared = {variable.name for variable in variables}
    scannable = _SQL_LITERALS_AND_COMMENTS.sub(lambda match: " " * len(match.group(0)), code)
    used = sorted({match.group(1) for match in _BARE_PLACEHOLDER.finditer(scannable)} & declared)
    if used:
        raise NotebookVariableError(
            f"Notebook variables ({', '.join(used)}) can't be used in a raw query. "
            "Turn off 'send raw query' to run it as HogQL, or write the value into the SQL."
        )


def build_notebook_variables(items: list[dict[str, Any]], timezone_info: ZoneInfo) -> list[NotebookVariable]:
    """Coerce the run request's declarations into variables with Python scalar values.

    Duplicates keep the first declaration, matching what the editor treats as the valid one.
    """
    variables: list[NotebookVariable] = []
    seen: set[str] = set()
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name or name in seen or name in RESERVED_VARIABLE_NAMES:
            continue
        seen.add(name)
        variables.append(
            NotebookVariable(name=name, value=_coerce_value(item.get("type"), item.get("value"), timezone_info))
        )
    return variables


def _coerce_value(variable_type: Any, value: Any, timezone_info: ZoneInfo) -> NotebookVariableValue:
    if value is None:
        return None
    if variable_type == "number":
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return value
        try:
            return float(str(value)) if "." in str(value) else int(str(value))
        except ValueError:
            return None
    if variable_type == "boolean":
        return value if isinstance(value, bool) else str(value).strip().lower() == "true"
    if variable_type == "date":
        text = str(value).strip()
        # A relative value ("-7d", "mStart") is resolved against the team's timezone, exactly as
        # an insight's date variable is; an absolute date stays a string the engine casts.
        return relative_date_parse(text, timezone_info) if is_relative_date_value(text) else text
    return str(value)


def python_variable_bindings(variables: list[NotebookVariable]) -> dict[str, Any]:
    """The name -> value map a Python cell gets bound into its kernel namespace.

    Dates go over as ISO strings: the payload is JSON on its way to the sandbox, and a
    string the user can parse beats a silently dropped value.
    """
    return {
        variable.name: variable.value.isoformat() if isinstance(variable.value, datetime | date) else variable.value
        for variable in variables
        if variable.name
    }
