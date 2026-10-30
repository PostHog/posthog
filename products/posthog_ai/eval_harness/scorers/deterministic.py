from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from posthog.dataclasses import frozen

from products.posthog_ai.eval_harness.log_parser import LogParser, ToolCall, is_schema_discovery_call

from .contract import Score, Scorer

QUERY_TOOL_PREFIX = "query-"
"""Prefix marking a typed query runner. The MCP server treats every ``query-*``
tool as a typed runner (see the ``query-run`` fallback in ``tools/exec.ts``),
so new runners are covered without an enumerated list going stale."""

EXECUTE_SQL_TOOL = "execute-sql"


def is_answer_query_tool(name: str) -> bool:
    """True when a tool produces a query result that can answer the user's question.

    The typed ``query-*`` runners (trends, funnel, retention, stickiness,
    lifecycle, paths, web analytics, llm-trace, and their ``-actors``
    variants) and arbitrary ``execute-sql`` are the answer-producing tools.
    Discovery, schema, and skill calls (``ToolSearch``, ``read-data-schema``,
    bare ``exec``) are intermediary: they run constantly in a healthy run and
    never count as the answer.
    """
    return name == EXECUTE_SQL_TOOL or name.startswith(QUERY_TOOL_PREFIX)


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


def _parser_for(output: dict[str, Any] | None) -> LogParser | None:
    raw_log = (output or {}).get("raw_log")
    if not raw_log:
        return None
    return LogParser.cached(raw_log, initial_prompt=(output or {}).get("prompt", "") or "")


def _call_order(call: ToolCall) -> int:
    return call.sequence if call.sequence is not None else call.position


def _query(call: ToolCall) -> str:
    query = call.input.get("query")
    return query if isinstance(query, str) else ""


def _spec(expected: dict | None, name: str) -> dict[str, Any] | None:
    spec = expected.get(name) if isinstance(expected, dict) else None
    return spec if isinstance(spec, dict) else None


def _successful_data_queries(parser: LogParser) -> list[ToolCall]:
    """Successful SQL that reads data, in call order. Schema lookups against information_schema are excluded."""
    return sorted(
        (
            call
            for call in parser.get_tool_calls(EXECUTE_SQL_TOOL)
            if not call.is_error and not is_schema_discovery_call(call)
        ),
        key=_call_order,
    )


@frozen
class ToolMatch:
    """Selects tool calls by normalized name, MCP server, or SQL text. Every set criterion must hold."""

    names: frozenset[str] = frozenset()
    server: str | None = None
    query_pattern: str | None = None
    """Case-insensitive regex searched in the call's ``query`` input."""

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
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        calls = sorted((call for call in parser.get_tool_calls() if not call.is_error), key=_call_order)
        after_calls = [call for call in calls if self.after.matches(call)]
        if not after_calls:
            return Score(name=self._name(), score=None, metadata={"reason": "No guarded call ran"})
        before_calls = [call for call in calls if self.before.matches(call)]
        first_before = _call_order(before_calls[0]) if before_calls else None
        early = [call for call in after_calls if first_before is None or _call_order(call) < first_before]
        return Score(
            name=self._name(),
            score=0.0 if early else 1.0,
            metadata={
                "guarded_calls": len(after_calls),
                "required_calls": len(before_calls),
                "calls_before_requirement": [call.name for call in early],
            },
        )


def _table_aliases(entry: object) -> list[str]:
    if isinstance(entry, str):
        return [entry]
    if isinstance(entry, list) and all(isinstance(alias, str) for alias in entry):
        return entry
    return []


class SourcesConsulted(Scorer):
    """Fraction of ``expected[name]["tables"]`` that a successful data query read.

    An entry is a table name, or a list of names one table answers to (a synced table answers to
    ``postgres_x`` and ``postgres.x``), and a read of any of them counts. ``score=None`` when the case
    does not request the check.
    """

    def __init__(self, *, name: str = "sources_consulted"):
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        tables = spec.get("tables")
        if not isinstance(tables, list) or not tables:
            return Score(name=self._name(), score=0.0, metadata={"reason": "invalid expected metadata"})
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        queries = [_query(call) for call in _successful_data_queries(parser)]
        read, missing = [], []
        for entry in tables:
            aliases = _table_aliases(entry)
            (read if any(reads_table(query, aliases) for query in queries) else missing).append(entry)
        return Score(name=self._name(), score=len(read) / len(tables), metadata={"read": read, "missing": missing})


class SourcesAvoided(Scorer):
    """Binary scorer: did the agent keep the tables in ``expected[name]["tables"]`` out of its data queries?

    Entries take the same names or alias lists as ``SourcesConsulted``.

    ``"scope": "answer"`` checks only the last successful data query, so a case can let the agent inspect a
    table (to find it empty, say) as long as the answer does not come from it. The default scope checks every
    successful data query.
    """

    def __init__(self, *, name: str = "sources_avoided"):
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        tables = spec.get("tables")
        if not isinstance(tables, list) or not tables:
            return Score(name=self._name(), score=0.0, metadata={"reason": "invalid expected metadata"})
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        queries = [_query(call) for call in _successful_data_queries(parser)]
        if spec.get("scope") == "answer":
            if not queries:
                return Score(name=self._name(), score=None, metadata={"reason": "No successful data query"})
            queries = queries[-1:]
        names = [alias for entry in tables for alias in _table_aliases(entry)]
        offending = [query for query in queries if reads_table(query, names)]
        return Score(name=self._name(), score=0.0 if offending else 1.0, metadata={"offending_queries": offending})


class ServerUsed(Scorer):
    """Binary scorer: did at least one call to the MCP server in ``expected[name]["server"]`` succeed?

    The server is the ``<server>`` in an ``mcp__<server>__<tool>`` raw tool name.
    """

    def __init__(self, *, name: str = "server_used"):
        self._label = name

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        server = spec.get("server")
        if not isinstance(server, str) or not server:
            return Score(name=self._name(), score=0.0, metadata={"reason": "invalid expected metadata"})
        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log"})
        calls = [call.name for call in parser.get_tool_calls() if not call.is_error and call.server == server]
        return Score(name=self._name(), score=1.0 if calls else 0.0, metadata={"calls": calls})
