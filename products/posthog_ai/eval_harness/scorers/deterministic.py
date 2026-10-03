from __future__ import annotations

from collections.abc import Iterable

from products.posthog_ai.eval_harness.log_parser import LogParser, is_schema_discovery_call

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
