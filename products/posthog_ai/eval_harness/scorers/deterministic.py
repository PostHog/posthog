from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, TypeGuard

from posthog.dataclasses import frozen

from products.posthog_ai.eval_harness.log_parser import (
    EXECUTE_SQL_TOOL_NAME,
    LogParser,
    ToolCall,
    is_answer_query_tool,
    is_schema_discovery_call,
)

from .contract import Score, Scorer


class ExitCodeZero(Scorer):
    """Binary scorer: did the agent process exit cleanly (code 0)?"""

    def _name(self) -> str:
        return "exit_code_zero"

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output"})
        exit_code = output.get("exit_code", -1)
        return Score(
            name=self._name(),
            score=1.0 if exit_code == 0 else 0.0,
            metadata={"exit_code": exit_code},
        )


class NoToolCall(Scorer):
    """Binary scorer: did the agent avoid successfully calling any forbidden tool?

    Constructed with a set of tool names that must never be successfully
    invoked. Walks the parsed tool-call list from ``LogParser`` and scores
    ``0.0`` if any successful (``is_error=False``) call's normalized name
    is in the forbidden set. Failed calls are allowed — the model is free
    to attempt and fail.

    Typical use: sandbox hygiene — forbid MCP tools that would persist state
    outside the disposable team (e.g. ``insight-create``, ``insight-update``).
    """

    forbidden: frozenset[str]
    _label: str

    def __init__(self, forbidden: Iterable[str], *, name: str = "no_forbidden_tool_call"):
        self.forbidden = frozenset(forbidden)
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser.cached(raw_log, initial_prompt=output.get("prompt", "") or "")
        successful_calls: list[str] = [
            call.name for call in parser.get_tool_calls() if not call.is_error and call.name in self.forbidden
        ]
        if successful_calls:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"forbidden_tools_called": successful_calls},
            )
        return Score(name=self._name(), score=1.0, metadata={})


class AnswerToolCallNot(Scorer):
    """Binary scorer: did the agent's *answer* come from a tool not in the forbidden set?

    Reading only the final successful call fails a run whose answer came from
    a typed tool but that closed on an ``execute-sql`` validation call. This
    scorer reads the *answer-producing* call instead.

    A call counts as answer-producing when it succeeded, is a query-producing
    tool (``is_answer_query_tool``: a typed ``query-*`` runner or
    ``execute-sql``), and is not a schema discovery lookup
    (``is_schema_discovery_call`` drops ``execute-sql`` queries against
    ``information_schema``). Intermediary calls like ``ToolSearch``,
    ``read-data-schema``, and bare ``exec`` never count. Among the answer
    calls, a call whose name is in ``preferred`` wins over every other: when
    the agent used a typed ``query-*`` tool, that tool is the answer and a
    trailing ``execute-sql`` is treated as validation. Only when no preferred
    tool ran does the last remaining answer call count.

    Scores ``0.0`` when the answer call's name is in the forbidden set, else
    ``1.0``. ``score=None`` when nothing answer-producing ran.
    """

    forbidden: frozenset[str]
    preferred: frozenset[str]
    _label: str

    def __init__(
        self,
        forbidden: str | Iterable[str],
        preferred: Iterable[str],
        *,
        name: str = "answer_tool_call_not_forbidden",
    ):
        if isinstance(forbidden, str):
            self.forbidden = frozenset({forbidden})
        else:
            self.forbidden = frozenset(forbidden)
        self.preferred = frozenset(preferred)
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser.cached(raw_log, initial_prompt=output.get("prompt", "") or "")
        answer_calls = [
            call
            for call in parser.get_tool_calls()
            if not call.is_error and is_answer_query_tool(call.name) and not is_schema_discovery_call(call)
        ]
        if not answer_calls:
            return Score(name=self._name(), score=None, metadata={"reason": "No answer-producing tool call"})

        typed = [call for call in answer_calls if call.name in self.preferred]
        answer = typed[-1] if typed else answer_calls[-1]

        if answer.name in self.forbidden:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"answer_tool_call": answer.name},
            )
        return Score(name=self._name(), score=1.0, metadata={"answer_tool_call": answer.name})


class RequiredToolCall(Scorer):
    """Binary scorer: did the agent successfully invoke at least one required tool?

    Constructed with a set of tool names — at least one of them must appear
    as a successful (``is_error=False``) call from ``LogParser.get_tool_calls``.
    Failed calls don't count; the model must have actually received a
    non-error result.

    Typical use: agent hygiene — require ``read-data-schema`` so the agent
    verifies an event/property exists in the team before running a query.
    """

    required: frozenset[str]
    _label: str

    def __init__(self, required: Iterable[str], *, name: str = "required_tool_call"):
        self.required = frozenset(required)
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser.cached(raw_log, initial_prompt=output.get("prompt", "") or "")
        seen: list[str] = [
            call.name for call in parser.get_tool_calls() if not call.is_error and call.name in self.required
        ]
        if seen:
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"required_tools_called": sorted(set(seen))},
            )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": "No required tool call found", "required": sorted(self.required)},
        )


# A table name inside a string literal is a catalog filter such as `WHERE table_name = '...'`, not a read.
_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'")


def reads_table(query: str, names: Iterable[str]) -> bool:
    """True when the query reads one of the named tables outside a string literal.

    The guards stop ``crm_deals`` from matching ``crm_deals_v3`` or a longer dotted name.
    """
    code = _STRING_LITERAL.sub("''", query.lower())
    return any(re.search(rf"(?<![\w.]){re.escape(name.lower())}(?![\w])", code) for name in names)


def parser_for(output: dict[str, Any] | None) -> LogParser | None:
    """The cached parser for the case's raw log, or ``None`` when the run left no log."""
    raw_log = (output or {}).get("raw_log")
    if not raw_log:
        return None
    return LogParser.cached(raw_log, initial_prompt=(output or {}).get("prompt", "") or "")


def call_order(call: ToolCall) -> int:
    """The call's place in the run. ``position`` counts messages, so it cannot order parallel calls."""
    if call.sequence is None:
        raise ValueError(f"Tool call {call.call_id} has no sequence, so the log cannot order it")
    return call.sequence


def _query(call: ToolCall) -> str:
    query = call.input.get("query")
    return query if isinstance(query, str) else ""


def expected_spec(expected: dict | None, name: str) -> dict[str, Any] | None:
    """The scorer's entry in ``expected``, or ``None`` when the case does not request the scorer."""
    spec = expected.get(name) if isinstance(expected, dict) else None
    return spec if isinstance(spec, dict) else None


def _successful_data_queries(parser: LogParser) -> list[ToolCall]:
    """Successful SQL that reads data, in call order. Schema lookups against information_schema are excluded."""
    return sorted(
        (
            call
            for call in parser.get_tool_calls(EXECUTE_SQL_TOOL_NAME)
            if not call.is_error and not is_schema_discovery_call(call)
        ),
        key=call_order,
    )


@frozen
class ToolMatch:
    """Selects tool calls by normalized name, MCP server, or SQL text. Every set criterion must hold."""

    names: frozenset[str] = frozenset()
    server: str | None = None
    query_pattern: str | None = None
    """Case-insensitive regex searched in the call's ``query`` input."""

    def __post_init__(self) -> None:
        if not self.names and self.server is None and self.query_pattern is None:
            raise ValueError("ToolMatch needs at least one criterion, or it matches every call")
        if self.query_pattern is not None:
            re.compile(self.query_pattern)

    def matches(self, call: ToolCall) -> bool:
        if self.names and call.name not in self.names:
            return False
        if self.server is not None and call.server != self.server:
            return False
        if self.query_pattern is not None and not re.search(self.query_pattern, _query(call), re.IGNORECASE):
            return False
        return True


class ToolOrder(Scorer):
    """Binary scorer: did every successful ``after`` call follow at least one successful ``before`` call?

    The generic form of "look up X before doing Y". Order is the run's tool-call sequence, so parallel calls
    in one assistant message are still ordered. ``score=None`` when no ``after`` call succeeded, because the
    precedence rule only applies to a run that did the guarded thing.
    """

    def __init__(self, before: ToolMatch, after: ToolMatch, *, name: str):
        self.before = before
        self.after = after
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected=None, **kwargs) -> Score:
        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        calls = sorted((call for call in parser.get_tool_calls() if not call.is_error), key=call_order)
        after_calls = [call for call in calls if self.after.matches(call)]
        if not after_calls:
            return Score(name=self._name(), score=None, metadata={"reason": "No guarded call ran"})
        before_calls = [call for call in calls if self.before.matches(call)]
        # A strict order, so a call that both matchers accept cannot satisfy its own prerequisite.
        early = [
            call for call in after_calls if not any(call_order(prior) < call_order(call) for prior in before_calls)
        ]
        return Score(
            name=self._name(),
            score=0.0 if early else 1.0,
            metadata={
                "guarded_calls": len(after_calls),
                "required_calls": len(before_calls),
                "calls_before_requirement": [call.name for call in early],
            },
        )


TableEntry = str | list[str]
"""A table name, or the names one table answers to (a synced table answers to ``postgres_x`` and ``postgres.x``)."""


def _table_aliases(entry: TableEntry) -> list[str]:
    return [entry] if isinstance(entry, str) else entry


def _valid_tables(tables: object) -> TypeGuard[list[TableEntry]]:
    """A non-empty list where each entry is a table name or a non-empty list of aliases, none of them empty."""
    if not isinstance(tables, list) or not tables:
        return False
    return all(
        (isinstance(entry, str) and bool(entry))
        or (isinstance(entry, list) and bool(entry) and all(isinstance(alias, str) and alias for alias in entry))
        for entry in tables
    )


@frozen
class _TableCheck:
    spec: dict[str, Any]
    tables: list[TableEntry]
    queries: list[str]
    """The text of each successful data query, in call order."""


def _table_check(name: str, output: dict | None, expected: dict | None) -> Score | _TableCheck:
    """The requested tables and the run's data queries, or the ``Score`` that ends the check early."""
    spec = expected_spec(expected, name)
    if spec is None:
        return Score(name=name, score=None, metadata={"reason": "not requested"})
    tables = spec.get("tables")
    if not _valid_tables(tables):
        return Score(name=name, score=0.0, metadata={"reason": "invalid expected metadata"})
    parser = parser_for(output)
    if parser is None:
        return Score(name=name, score=0.0, metadata={"reason": "No raw log"})
    return _TableCheck(spec=spec, tables=tables, queries=[_query(call) for call in _successful_data_queries(parser)])


class SourcesConsulted(Scorer):
    """Fraction of ``expected[name]["tables"]`` that a successful data query read.

    Each entry is a ``TableEntry``, and a read of any of its names counts. ``score=None`` when the case
    does not request the check.
    """

    def __init__(self, *, name: str = "sources_consulted"):
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        check = _table_check(self._name(), output, expected)
        if isinstance(check, Score):
            return check
        read: list[TableEntry] = []
        missing: list[TableEntry] = []
        for entry in check.tables:
            aliases = _table_aliases(entry)
            (read if any(reads_table(query, aliases) for query in check.queries) else missing).append(entry)
        return Score(
            name=self._name(), score=len(read) / len(check.tables), metadata={"read": read, "missing": missing}
        )


ANY_CLEAN_QUERY_SCOPE = "any_clean_query"


class SourcesAvoided(Scorer):
    """Binary scorer: did the agent keep the tables in ``expected[name]["tables"]`` out of its data queries?

    Entries take the same names or alias lists as ``SourcesConsulted``. The default scope fails when any
    successful data query reads a listed table.

    ``"scope": "any_clean_query"`` fails only when every successful data query reads a listed table, so the agent
    can inspect one (to find it empty, say) before or after the query that answers. Pair it with a value check or
    a judge, because this scope cannot tell which query the answer came from. ``score=None`` when no data query
    succeeded, because a run that read nothing avoided nothing.
    """

    def __init__(self, *, name: str = "sources_avoided"):
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        check = _table_check(self._name(), output, expected)
        if isinstance(check, Score):
            return check
        scope = check.spec.get("scope")
        if scope not in (None, ANY_CLEAN_QUERY_SCOPE):
            return Score(name=self._name(), score=0.0, metadata={"reason": "invalid expected metadata"})
        if not check.queries:
            return Score(name=self._name(), score=None, metadata={"reason": "No successful data query"})
        names = [alias for entry in check.tables for alias in _table_aliases(entry)]
        offending = [query for query in check.queries if reads_table(query, names)]
        if scope == ANY_CLEAN_QUERY_SCOPE:
            passed = len(offending) < len(check.queries)
        else:
            passed = not offending
        return Score(name=self._name(), score=1.0 if passed else 0.0, metadata={"offending_queries": offending})


class ServerUsed(Scorer):
    """Binary scorer: did at least one call to the MCP server in ``expected[name]["server"]`` succeed?

    The server is the ``<server>`` in an ``mcp__<server>__<tool>`` raw tool name.
    """

    def __init__(self, *, name: str = "server_used"):
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = expected_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        server = spec.get("server")
        if not isinstance(server, str) or not server:
            return Score(name=self._name(), score=0.0, metadata={"reason": "invalid expected metadata"})
        parser = parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        calls = [call.name for call in parser.get_tool_calls() if not call.is_error and call.server == server]
        return Score(name=self._name(), score=1.0 if calls else 0.0, metadata={"calls": calls})
