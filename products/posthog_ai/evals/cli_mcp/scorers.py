"""Deterministic scorers for the cli_mcp evals.

Each case carries its per-scorer params under the scorer's ``_name()``
in ``expected``, mirroring the convention used by
``LookupIdInOutput`` (see ``retrieval/scorers.py``):

    expected = {
        "called_target_tool": {"tool": "notebooks-create"},
    }

Scorers default to ``score=None`` when their key is missing —
unrelated cases don't drag the rollup down.

* ``CalledTargetTool`` — did the agent successfully invoke
  ``expected[<scorer_name>]["tool"]`` at least once? Returns 1.0/0.0.
* ``FirstRelevantTool`` — in the earliest turn where the agent used one of a
  supplied set of comparable tools, did it use only the expected one?
  Returns 1.0/0.0.
* ``RecoveredToCorrectTool`` — when prompted to use a wrong tool name
  (deprecated or typo'd), did the agent end up calling a correct
  replacement?
* ``DrilledIntoSchema`` — did the agent drill into every named field
  via ``schema <tool> <field>`` before the final ``call``?
* ``RetrievedSchemaPath`` — did the agent successfully retrieve an exact
  nested schema path via ``schema <tool> <path>``?
* ``PreferredSearchOverTools`` — did the agent prefer ``search`` over
  the bare ``tools`` listing for discovery?
* ``InfoBeforeCall`` — was every successful call to the target tool
  preceded by ``info <tool>`` in the same run?
* ``VerifiedEventBeforeQuery`` — did the agent run ``read-data-schema``
  before any successful ``query-*`` call?
* ``DidNotCiteRawSqlAfterTypedQuery`` — after a typed query tool succeeded,
  did the final answer avoid hand-writing the equivalent raw SQL?
* ``ChartShown`` — did the user see the query result as a chart, through
  ``render-ui``, the client's inline view, or a chart link in the answer?
* ``ChartFromTypedQuery`` — was that chart the typed query, not rewritten SQL?
* ``NoMarkdownDataTable`` — did the agent avoid retyping the result as a long
  Markdown table?
"""

from __future__ import annotations

import re
import json
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor

from products.posthog_ai.backend.exec_commands import INFO_SYNTHETIC_PREFIX
from products.posthog_ai.eval_harness.log_parser import EXEC_TOOL_NAME, LogParser, ToolCall, is_schema_discovery_call
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

__all__ = [
    "CalledTargetTool",
    "ChartFromTypedQuery",
    "ChartShown",
    "DidNotCiteRawSqlAfterTypedQuery",
    "DidNotRenderUi",
    "DrilledIntoSchema",
    "ExecBeforeRender",
    "InfoBeforeCall",
    "FirstRelevantTool",
    "NoMarkdownDataTable",
    "PreferredSearchOverTools",
    "RanPythonPostProcessing",
    "RecoveredToCorrectTool",
    "RenderedEntityUi",
    "RetrievedSchemaPath",
    "SurfacedGeneratedAppUrl",
    "UsedJsonOutputFormat",
    "VerifiedEventBeforeQuery",
]

# URLs stop at whitespace and the delimiters that wrap them in Markdown/JSON/TOON, so the captured
# string is the bare link — robust to `[text](url)`, `"url"`, JSON-escaped `\"url\"`, trailing
# punctuation, etc. The backslash exclusion matters: tool results arrive JSON-escaped, so without it
# the capture keeps a trailing `\` and never substring-matches the (unescaped) final message.
_URL_RE = re.compile(r"https?://[^\s\"'`)\]<>\\]+")

# Matches a `<hogql>` citation tag or a fenced ```sql block — the two shapes an
# agent uses to hand-write a raw query in its final answer instead of trusting
# a typed query tool's own structured result.
_RAW_SQL_CITATION_RE = re.compile(r"<hogql\b|```sql\b", re.IGNORECASE)

RENDER_UI_TOOL_NAME = "render-ui"
"""Normalized name of the umbrella render tool (``mcp__<server>__render-ui`` → ``render-ui``).

Registered only in single-exec (``cli``) MCP mode — see
``services/mcp/src/tools/render-ui.ts`` and its prompt
``services/mcp/src/templates/render-ui-prompt.md``."""


def _read_tool(expected: dict | None, scorer_name: str) -> str | None:
    """Look up ``expected[scorer_name]["tool"]`` with permissive validation."""
    if not isinstance(expected, dict):
        return None
    spec = expected.get(scorer_name)
    if not isinstance(spec, dict):
        return None
    target = spec.get("tool")
    return target if isinstance(target, str) and target else None


def _read_spec(expected: dict | None, scorer_name: str) -> dict | None:
    """Look up the per-scorer params dict ``expected[scorer_name]`` (any shape)."""
    if not isinstance(expected, dict):
        return None
    spec = expected.get(scorer_name)
    return spec if isinstance(spec, dict) else None


def _exec_command_head(call: ToolCall) -> tuple[str, str]:
    """Return ``(verb, rest)`` for a raw ``exec`` call's command string.

    Empty tuple for non-``exec`` or already-unwrapped calls. Lets scorers
    inspect the ``search`` / ``schema`` / ``tools`` verbs that
    ``parse_exec_command`` intentionally drops on the floor.
    """
    if call.is_exec_unwrapped or call.name != EXEC_TOOL_NAME:
        return ("", "")
    cmd = call.input.get("command", "")
    if not isinstance(cmd, str):
        return ("", "")
    head, _, rest = cmd.strip().partition(" ")
    return (head.lower(), rest.strip())


def _build_parser(output: dict | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser.cached(raw_log, initial_prompt=output.get("prompt", "") or "")


class CalledTargetTool(Scorer):
    """Binary: did the agent successfully invoke ``expected[<scorer_name>]["tool"]``?"""

    def _name(self) -> str:
        return "called_target_tool"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        if not output:
            return Score(name=self._name(), score=None, metadata={"reason": "No output"})
        target = _read_tool(expected, self._name())
        if not target:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"No {self._name()}.tool on case"},
            )
        raw_log = output.get("raw_log")
        if not raw_log:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        parser = LogParser.cached(raw_log, initial_prompt=output.get("prompt", "") or "")
        for call in parser.get_tool_calls(target):
            if not call.is_error:
                return Score(name=self._name(), score=1.0, metadata={"tool": target, "call_id": call.call_id})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": f"Tool '{target}' was never successfully called", "tool": target},
        )


class DidNotCiteRawSqlAfterTypedQuery(Scorer):
    """Binary: after a typed query tool succeeded, did the answer avoid raw SQL?

    ``expected = {"did_not_cite_raw_sql_after_typed_query": {"tool": "query-trends"}}``

    A typed query tool (``query-trends`` and friends) already returns a
    structured, renderable result — there is no reason for the final answer
    to also hand-write the equivalent SQL. Doing so anyway reads as a routing
    win under ``CalledTargetTool`` while the underlying reasoning is still
    SQL-first; this scorer catches that gap.

    Looks for a ``<hogql`` citation tag or a fenced ```sql block in the final
    assistant message. Score 1.0 if the tool succeeded and neither appears,
    0.0 if either appears. ``None`` if ``tool`` was never called successfully
    (that gap is caught by ``CalledTargetTool``).
    """

    def _name(self) -> str:
        return "did_not_cite_raw_sql_after_typed_query"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        target = _read_tool(expected, self._name())
        if not target:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()}.tool on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        called = any(not call.is_error for call in parser.get_tool_calls(target))
        if not called:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"Tool '{target}' was never successfully called", "tool": target},
            )

        last_message = (output or {}).get("last_message") or ""
        if not isinstance(last_message, str):
            last_message = str(last_message)

        match = _RAW_SQL_CITATION_RE.search(last_message)
        if match:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "Final answer cited raw SQL after a typed query tool already succeeded",
                    "tool": target,
                    "matched": match.group(0),
                },
            )
        return Score(name=self._name(), score=1.0, metadata={"tool": target})


class FirstRelevantTool(Scorer):
    """Binary: did the earliest turn that used ``relevant_tools`` use only the target?

    ``execute-sql`` calls against ``system.information_schema.*`` are skipped:
    the MCP instructions require that catalog lookup before an answer query, so
    counting it as the route would score the mandated discovery step rather
    than the tool the agent picked to answer with.

    ``position`` is the index of the enclosing assistant message, so every call
    the agent emitted in one response shares it. Such calls are simultaneous —
    none of them saw another's result — so there is no first among them, and
    picking one by block order would grade the order the model happened to
    write them in. This scorer grades the whole batch instead: it passes only
    when every relevant call in the earliest turn used the target. A turn that
    fires a typed runner and ``execute-sql`` together is a hedge, not a route,
    and fails whichever of the two the case expects.

    ``turn=N`` (1-indexed) grades one turn of a multi-turn case instead of the
    whole conversation: it reads slice ``N - 1`` of the runner's ``turn_logs``
    (one cumulative-log slice per completed turn) and seeds the parser with
    that turn's prompt from ``turn_prompts``. A missing slice scores ``None``,
    not ``0.0`` — a turn that never ran is infrastructure noise, not an agent
    routing failure.

    ``tool`` overrides the per-case ``expected[...]["tool"]`` target. A
    multi-turn case carries one ``expected`` dict for every turn, so a scorer
    whose turn has a different target from the rest (e.g. a turn that must
    route to ``execute-sql`` while the others expect ``query-trends``) passes
    its own.

    Each turn's scorer needs a distinct output name, or the four per-turn
    ``Score`` objects collide on one key: the per-case ``scores`` dict keeps
    only the last turn's value, and the rollup blends the manipulation-check
    turn into the recovery metric. So a ``turn`` scorer defaults its name to
    ``first_relevant_tool_t{turn}`` (override with ``name``). The per-case
    ``expected`` lookup still uses the shared ``first_relevant_tool`` key, so a
    renamed scorer keeps finding its target.
    """

    _EXPECTED_KEY = "first_relevant_tool"

    def __init__(
        self,
        *,
        relevant_tools: frozenset[str],
        turn: int | None = None,
        tool: str | None = None,
        name: str | None = None,
    ) -> None:
        self.relevant_tools = relevant_tools
        self.turn = turn
        self.tool = tool
        if name is not None:
            self._label = name
        elif turn is not None:
            self._label = f"{self._EXPECTED_KEY}_t{turn}"
        else:
            self._label = self._EXPECTED_KEY

    def _name(self) -> str:
        return self._label

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        target = self.tool or _read_tool(expected, self._EXPECTED_KEY)
        if not target:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._EXPECTED_KEY}.tool on case"})

        raw_log = (output or {}).get("raw_log")
        initial_prompt = ((output or {}).get("prompt") or "") if isinstance(output, dict) else ""
        if self.turn is not None:
            # Grade one turn of a multi-turn case. Turn logs are cumulative-log
            # slices: they carry no user_message line, so seed the parser with the
            # turn's own prompt. A missing slice means the turn never ran — infra
            # noise, not an agent failure, so skip rather than score 0.
            turn_logs = (output or {}).get("turn_logs")
            turn_prompts = (output or {}).get("turn_prompts")
            if not isinstance(turn_logs, list) or self.turn < 1 or self.turn > len(turn_logs):
                return Score(
                    name=self._name(),
                    score=None,
                    metadata={"reason": f"No turn {self.turn} log slice", "tool": target},
                )
            raw_log = turn_logs[self.turn - 1]
            if isinstance(turn_prompts, list) and len(turn_prompts) >= self.turn:
                prompt = turn_prompts[self.turn - 1]
                initial_prompt = prompt if isinstance(prompt, str) else ""
            if not raw_log:
                return Score(
                    name=self._name(),
                    score=None,
                    metadata={"reason": f"Turn {self.turn} log slice is empty", "tool": target},
                )

        if not raw_log:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log", "tool": target})
        parser = LogParser.cached(raw_log, initial_prompt=initial_prompt)

        candidates = [
            call for call in parser.get_tool_calls() if not call.is_error and call.name in self.relevant_tools
        ]
        relevant = [call for call in candidates if not is_schema_discovery_call(call)]
        skipped_discovery = len(candidates) - len(relevant)
        if not relevant:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "No successful relevant tool calls",
                    "tool": target,
                    "skipped_discovery_calls": skipped_discovery,
                },
            )

        first_position = min(call.position for call in relevant)
        first_turn = [call for call in relevant if call.position == first_position]
        turn_tools = sorted({call.name for call in first_turn})
        metadata: dict[str, object] = {
            "expected_tool": target,
            "first_relevant_tool": turn_tools[0] if len(turn_tools) == 1 else None,
            "first_relevant_tools": turn_tools,
            "call_ids": [call.call_id for call in first_turn],
            "skipped_discovery_calls": skipped_discovery,
        }
        if turn_tools == [target]:
            return Score(name=self._name(), score=1.0, metadata=metadata)
        if len(turn_tools) > 1:
            metadata["reason"] = "The earliest relevant turn selected several tools at once"
        return Score(name=self._name(), score=0.0, metadata=metadata)


def _attempted_tool(call: ToolCall, wrong: str) -> bool:
    """True if a tool call represents an attempt against the ``wrong`` name.

    Counts (a) successful or failed unwrapped calls whose inner name matches,
    (b) ``info <wrong>`` synthetic entries, and (c) raw ``exec`` calls whose
    ``call <wrong>`` / ``info <wrong>`` command targets ``wrong`` but didn't
    parse cleanly enough to unwrap.
    """
    if call.name == wrong:
        return True
    if call.name == f"{INFO_SYNTHETIC_PREFIX}{wrong}":
        return True
    head, rest = _exec_command_head(call)
    if head not in ("call", "info"):
        return False
    if head == "call" and rest.startswith("--json"):
        rest = rest[len("--json") :].lstrip()
    target, _, _ = rest.partition(" ")
    return target.strip() == wrong


class RecoveredToCorrectTool(Scorer):
    """Binary: prompted with a wrong tool name, did the agent recover?

    ``expected = {"recovered_to_correct_tool":
        {"wrong": "query-run", "correct_any_of": ["query-trends", "execute-sql"]}}``

    Score 1.0 if the agent both *attempted* the wrong tool AND eventually made
    a successful unwrapped call to one of ``correct_any_of``. 0.0 if attempted
    but never recovered. ``None`` if ``wrong`` was never attempted (the case
    didn't actually exercise the redirect path).
    """

    def _name(self) -> str:
        return "recovered_to_correct_tool"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _read_spec(expected, self._name())
        if not spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        wrong = spec.get("wrong")
        correct_any_of = spec.get("correct_any_of")
        if not isinstance(wrong, str) or not wrong:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'wrong' on spec"})
        if not isinstance(correct_any_of, list) or not correct_any_of:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'correct_any_of' on spec"})
        correct_set = {c for c in correct_any_of if isinstance(c, str) and c}

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls = parser.get_tool_calls()
        attempted = any(_attempted_tool(call, wrong) for call in calls)
        if not attempted:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"Wrong tool '{wrong}' was never attempted", "wrong": wrong},
            )

        for call in calls:
            if call.is_error:
                continue
            if call.name in correct_set:
                return Score(
                    name=self._name(),
                    score=1.0,
                    metadata={"wrong": wrong, "recovered_to": call.name, "call_id": call.call_id},
                )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "Wrong tool attempted but no successful call to a correct replacement",
                "wrong": wrong,
                "correct_any_of": sorted(correct_set),
            },
        )


class DrilledIntoSchema(Scorer):
    """Binary: did the agent drill into every named field via ``schema <tool> <field>``?

    ``expected = {"drilled_into_schema":
        {"tool": "query-trends", "fields": ["series", "breakdownFilter"]}}``

    Looks for raw ``exec`` calls whose ``command`` is ``schema <tool> <field>``
    or ``schema <tool> <field>.<sub>`` (dot-notation prefix counts). Score 1.0
    only if every required field was drilled, 0.0 otherwise with the missing
    fields in metadata. ``None`` if the spec is malformed.
    """

    def _name(self) -> str:
        return "drilled_into_schema"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _read_spec(expected, self._name())
        if not spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        tool = spec.get("tool")
        fields = spec.get("fields")
        if not isinstance(tool, str) or not tool:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'tool' on spec"})
        if not isinstance(fields, list) or not fields:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'fields' on spec"})
        required = [f for f in fields if isinstance(f, str) and f]

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        drilled: set[str] = set()
        for call in parser.get_tool_calls():
            head, rest = _exec_command_head(call)
            if head != "schema":
                continue
            schema_tool, _, field_path = rest.partition(" ")
            if schema_tool.strip() != tool:
                continue
            field_path = field_path.strip()
            if not field_path:
                continue
            top_field, _, _ = field_path.partition(".")
            top_field = top_field.strip()
            if top_field in required:
                drilled.add(top_field)

        missing = [f for f in required if f not in drilled]
        if missing:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "Required fields were not drilled via 'schema'",
                    "tool": tool,
                    "missing_fields": missing,
                    "drilled_fields": sorted(drilled),
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"tool": tool, "drilled_fields": sorted(drilled)},
        )


class RetrievedSchemaPath(Scorer):
    """Binary: did the agent successfully retrieve an exact nested schema path?

    ``expected = {"retrieved_schema_path":
        {"tool": "query-trends", "path": "series.properties"}}``

    Looks for a raw ``exec`` call whose ``command`` is exactly
    ``schema <tool> <path>``. Score 1.0 only when that call succeeded, 0.0
    when the path was attempted but failed or a different schema path was
    used, and ``None`` for malformed specs.
    """

    def _name(self) -> str:
        return "retrieved_schema_path"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _read_spec(expected, self._name())
        if not spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        tool = spec.get("tool")
        path = spec.get("path")
        if not isinstance(tool, str) or not tool:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'tool' on spec"})
        if not isinstance(path, str) or not path:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'path' on spec"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        schema_attempts: list[dict[str, object]] = []
        for call in parser.get_tool_calls():
            head, rest = _exec_command_head(call)
            if head != "schema":
                continue
            schema_tool, _, field_path = rest.partition(" ")
            schema_tool = schema_tool.strip()
            field_path = field_path.strip()
            schema_attempts.append(
                {
                    "tool": schema_tool,
                    "path": field_path,
                    "is_error": call.is_error,
                    "call_id": call.call_id,
                }
            )
            if schema_tool != tool or field_path != path:
                continue
            if call.is_error:
                return Score(
                    name=self._name(),
                    score=0.0,
                    metadata={
                        "reason": "Exact schema path was attempted but failed",
                        "tool": tool,
                        "path": path,
                        "call_id": call.call_id,
                    },
                )
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"tool": tool, "path": path, "call_id": call.call_id},
            )

        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "Exact schema path was not retrieved",
                "tool": tool,
                "path": path,
                "schema_attempts": schema_attempts,
            },
        )


class PreferredSearchOverTools(Scorer):
    """Binary: did the agent prefer ``search`` over the bare ``tools`` listing?

    Opt-in via presence of ``expected = {"preferred_search_over_tools": {}}``.

    Walks raw ``exec`` calls in chronological order. Score 1.0 if the first
    discovery action (``search`` or ``tools``) was ``search``, or if ``tools``
    was never used. 0.0 if ``tools`` came first or if ``tools`` was used
    without any ``search`` in the run. ``None`` if no discovery actions at all.
    """

    def _name(self) -> str:
        return "preferred_search_over_tools"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        if _read_spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} key on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls_by_position = sorted(parser.get_tool_calls(), key=lambda c: c.position)
        first_discovery: str | None = None
        used_search = False
        used_tools = False
        for call in calls_by_position:
            head, _ = _exec_command_head(call)
            if head not in ("search", "tools"):
                continue
            if first_discovery is None:
                first_discovery = head
            if head == "search":
                used_search = True
            else:
                used_tools = True

        if first_discovery is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No discovery actions"})
        if not used_tools:
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"first_discovery": first_discovery, "used_tools": False},
            )
        if first_discovery == "search":
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"first_discovery": "search", "used_tools": True, "used_search": used_search},
            )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "Bare 'tools' was the first discovery action",
                "first_discovery": "tools",
                "used_search": used_search,
            },
        )


class InfoBeforeCall(Scorer):
    """Binary: was every successful call to the target tool preceded by ``info <tool>``?

    ``expected = {"info_before_call": {"tool": "dashboard-create"}}``

    Walks tool calls in chronological order; for each successful unwrapped
    call to ``tool``, requires that an ``info <tool>`` synthetic entry
    appeared earlier. Score 1.0 if all qualifying calls were preceded, 0.0
    otherwise. ``None`` if ``tool`` was never called successfully (caught
    upstream by ``CalledTargetTool``).
    """

    def _name(self) -> str:
        return "info_before_call"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        target = _read_tool(expected, self._name())
        if not target:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()}.tool on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls = sorted(parser.get_tool_calls(), key=lambda c: c.position)
        info_synthetic = f"{INFO_SYNTHETIC_PREFIX}{target}"
        seen_info = False
        offenders: list[str] = []
        successful_calls = 0
        for call in calls:
            if call.name == info_synthetic and not call.is_error:
                seen_info = True
                continue
            if call.is_exec_unwrapped and call.name == target and not call.is_error:
                successful_calls += 1
                if not seen_info:
                    offenders.append(call.call_id)

        if successful_calls == 0:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"Target '{target}' never called successfully", "tool": target},
            )
        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "At least one call to target was not preceded by 'info <tool>'",
                    "tool": target,
                    "offenders": offenders,
                    "total_calls": successful_calls,
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"tool": target, "total_calls": successful_calls},
        )


class VerifiedEventBeforeQuery(Scorer):
    """Binary: did the agent run ``read-data-schema`` before any successful ``query_tool`` call?

    ``expected = {"verified_event_before_query": {"query_tool": "query-trends"}}``

    For each successful unwrapped call to ``query_tool``, requires that a
    successful ``read-data-schema`` call appeared earlier. Score 1.0 if all
    qualifying calls were preceded, 0.0 otherwise. ``None`` if ``query_tool``
    never called successfully.
    """

    SCHEMA_TOOL = "read-data-schema"

    def _name(self) -> str:
        return "verified_event_before_query"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _read_spec(expected, self._name())
        if not spec:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        query_tool = spec.get("query_tool")
        if not isinstance(query_tool, str) or not query_tool:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'query_tool' on spec"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls = sorted(parser.get_tool_calls(), key=lambda c: c.position)
        seen_schema = False
        offenders: list[str] = []
        successful_calls = 0
        for call in calls:
            if call.is_error:
                continue
            if call.is_exec_unwrapped and call.name == self.SCHEMA_TOOL:
                seen_schema = True
                continue
            if call.is_exec_unwrapped and call.name == query_tool:
                successful_calls += 1
                if not seen_schema:
                    offenders.append(call.call_id)

        if successful_calls == 0:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"Query tool '{query_tool}' never called successfully"},
            )
        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": f"'{query_tool}' was called without a prior successful '{self.SCHEMA_TOOL}'",
                    "query_tool": query_tool,
                    "offenders": offenders,
                    "total_calls": successful_calls,
                },
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"query_tool": query_tool, "total_calls": successful_calls},
        )


class UsedJsonOutputFormat(Scorer):
    """Binary: did the agent request raw JSON output for the named tool?

    ``expected = {"used_json_output_format": {"tool": "dashboards-get-all"}}``

    For every successful unwrapped call to ``tool``, requires
    ``requested_output_format == "json"``. The default is ``"optimized"``,
    which is fine for human-facing answers but lossy / token-truncated for
    Python post-processing — opting into ``"json"`` is the right move when
    the agent plans to parse results programmatically.

    Score 1.0 if at least one successful call to ``tool`` requested
    ``output_format == "json"``. 0.0 if every successful call used the
    default. ``None`` if the tool was never called successfully.
    """

    def _name(self) -> str:
        return "used_json_output_format"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        target = _read_tool(expected, self._name())
        if not target:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()}.tool on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        relevant = [call for call in parser.get_tool_calls(target) if not call.is_error and call.is_exec_unwrapped]
        if not relevant:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"No successful exec-unwrapped '{target}' calls", "tool": target},
            )

        json_calls = [call for call in relevant if call.requested_output_format == "json"]
        if json_calls:
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"tool": target, "json_calls": len(json_calls), "total_calls": len(relevant)},
            )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": f"All successful '{target}' calls used the default output format",
                "tool": target,
                "total_calls": len(relevant),
                "formats_seen": sorted({call.requested_output_format or "default" for call in relevant}),
            },
        )


class SurfacedGeneratedAppUrl(Scorer):
    """Binary: did the agent surface a url returned by ``generate-app-url`` verbatim?

    Opt-in via presence of ``expected = {"surfaced_generated_app_url": {}}``.

    The fix for hand-built 404 links is to resolve entity links through the
    ``generate-app-url`` tool and surface the ``url`` it returns verbatim,
    rather than guessing slugs (a person UUID lives at ``/persons/<uuid>``,
    not ``/person/...``) or retyping ids. This scorer finds every successful
    ``generate-app-url`` call, pulls the url out of its result, and checks the
    final assistant message contains at least one of them.

    Score 1.0 if a generated url was surfaced, 0.0 if the tool ran but its url
    was dropped or rewritten, ``None`` if the tool was never called (that gap
    is caught by ``CalledTargetTool``).
    """

    TOOL = "generate-app-url"

    def _name(self) -> str:
        return "surfaced_generated_app_url"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        if _read_spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} key on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        urls: set[str] = set()
        for call in parser.get_tool_calls(self.TOOL):
            if call.is_error:
                continue
            urls.update(_URL_RE.findall(call.output or ""))
        if not urls:
            return Score(
                name=self._name(),
                score=None,
                metadata={"reason": f"'{self.TOOL}' was never called successfully or returned no url"},
            )

        last_message = (output or {}).get("last_message") or ""
        if not isinstance(last_message, str):
            last_message = str(last_message)

        surfaced = sorted(url for url in urls if url in last_message)
        if surfaced:
            return Score(name=self._name(), score=1.0, metadata={"surfaced": surfaced})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "generate-app-url returned a url but it was not surfaced verbatim in the answer",
                "tool_urls": sorted(urls),
            },
        )


class RanPythonPostProcessing(Scorer):
    """Binary: did the agent actually run Python to post-process tool results?

    Opt-in via presence of ``expected = {"ran_python_post_processing": {}}``.

    Walks ``Bash`` tool calls and looks for one whose command contains
    ``python`` or ``python3`` (heuristic — matches ``python -c '...'``,
    ``python3 script.py``, ``cat ... | python3 -``, ``uv run python ...``).
    Score 1.0 if any successful Bash call ran Python, 0.0 otherwise.
    ``None`` if no Bash calls at all.
    """

    PYTHON_TOKENS: frozenset[str] = frozenset({"python", "python3"})

    def _name(self) -> str:
        return "ran_python_post_processing"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        if _read_spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} key on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        bash_calls = parser.get_tool_calls("Bash")
        if not bash_calls:
            return Score(name=self._name(), score=None, metadata={"reason": "No Bash calls"})

        for call in bash_calls:
            if call.is_error:
                continue
            cmd = call.input.get("command", "")
            if not isinstance(cmd, str):
                continue
            tokens = {part.split("/")[-1] for part in cmd.split() if part}
            if tokens & self.PYTHON_TOKENS:
                return Score(
                    name=self._name(),
                    score=1.0,
                    metadata={"matched_call_id": call.call_id},
                )
        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "No Bash call invoked python/python3",
                "bash_call_count": len(bash_calls),
            },
        )


def _render_ui_calls(parser: LogParser) -> list[ToolCall]:
    return parser.get_tool_calls(RENDER_UI_TOOL_NAME)


def _rendered_tool_name(call: ToolCall) -> str | None:
    """The ``tool_name`` a ``render-ui`` call asked to render, if present."""
    name = call.input.get("tool_name")
    return name if isinstance(name, str) and name else None


class RenderedEntityUi(Scorer):
    """Binary: did the agent render the expected entity via ``render-ui``?

    ``expected = {"rendered_entity_ui":
        {"tool_name_any_of": ["experiment-get", "experiment-timeseries-results"]}}``
    or ``{"rendered_entity_ui": {}}`` to accept any render.

    Score 1.0 when a successful ``render-ui`` call carried a ``tool_name`` in
    ``tool_name_any_of`` (or any ``tool_name`` when the list is omitted). 0.0
    otherwise, with what was actually rendered in metadata. ``None`` if the spec
    is absent. Mirrors the "strongly prefer rendering for entity-centric
    answers" rule in ``render-ui-prompt.md``.
    """

    def _name(self) -> str:
        return "rendered_entity_ui"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _read_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        allowed = spec.get("tool_name_any_of")
        allowed_set = {t for t in allowed if isinstance(t, str) and t} if isinstance(allowed, list) else None

        rendered: list[str] = []
        errored_matches: list[str] = []
        for call in _render_ui_calls(parser):
            tool_name = _rendered_tool_name(call)
            if tool_name is None:
                continue
            rendered.append(tool_name)
            if allowed_set is not None and tool_name not in allowed_set:
                continue
            if call.is_error:
                errored_matches.append(tool_name)
                continue
            return Score(
                name=self._name(),
                score=1.0,
                metadata={"rendered_tool_name": tool_name, "call_id": call.call_id},
            )

        return Score(
            name=self._name(),
            score=0.0,
            metadata={
                "reason": "render-ui was not called with an expected tool_name",
                "expected_any_of": sorted(allowed_set) if allowed_set else "any",
                "rendered_tool_names": rendered,
                "errored_matches": errored_matches,
            },
        )


class ExecBeforeRender(Scorer):
    """Binary: was every ``render-ui`` call preceded by a successful ``exec`` action?

    Opt-in via ``expected = {"exec_before_render": {}}``.

    ``render-ui`` is the final presentation step, never a discovery step — the
    agent must resolve the entity (look up its real ID) and confirm the data via
    ``exec`` (``search``/``info``/``schema``/``call``) first. For each
    ``render-ui`` call, requires a successful exec-derived call strictly earlier
    in the run. Score 1.0 if every render qualifies, 0.0 if any render fired with
    no prior exec (rendered before discovery / with a guessed input). ``None`` if
    ``render-ui`` was never called (covered by ``RenderedEntityUi``).
    """

    def _name(self) -> str:
        return "exec_before_render"

    @staticmethod
    def _is_exec_action(call: ToolCall) -> bool:
        if call.is_error:
            return False
        return call.is_exec_unwrapped or call.name == EXEC_TOOL_NAME or call.name.startswith(INFO_SYNTHETIC_PREFIX)

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        if _read_spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} key on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        calls = sorted(parser.get_tool_calls(), key=lambda c: c.position)
        render_calls = [c for c in calls if c.name == RENDER_UI_TOOL_NAME]
        if not render_calls:
            return Score(name=self._name(), score=None, metadata={"reason": "render-ui never called"})

        offenders: list[str] = []
        for render_call in render_calls:
            preceded = any(self._is_exec_action(c) and c.position < render_call.position for c in calls)
            if not preceded:
                offenders.append(render_call.call_id)

        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "render-ui fired before any successful exec call",
                    "offenders": offenders,
                    "render_calls": len(render_calls),
                },
            )
        return Score(name=self._name(), score=1.0, metadata={"render_calls": len(render_calls)})


class DidNotRenderUi(Scorer):
    """Binary: did the agent correctly avoid ``render-ui`` here?

    ``expected = {"did_not_render_ui": {}}`` penalizes any ``render-ui`` call;
    ``{"did_not_render_ui": {"tool_name_any_of": ["query-trends"]}}`` penalizes
    only renders that routed one of those tool names.

    Use for query/insight answers: ``query-*`` results render through their own
    app automatically and must not be passed to ``render-ui``. Score 1.0 when no
    offending ``render-ui`` call exists, 0.0 otherwise. ``None`` if the spec is
    absent.
    """

    def _name(self) -> str:
        return "did_not_render_ui"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _read_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} key on case"})

        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})

        allowed = spec.get("tool_name_any_of")
        target_set = {t for t in allowed if isinstance(t, str) and t} if isinstance(allowed, list) else None

        offenders: list[dict[str, object]] = []
        for call in _render_ui_calls(parser):
            tool_name = _rendered_tool_name(call)
            if target_set is None or (tool_name is not None and tool_name in target_set):
                offenders.append({"tool_name": tool_name, "call_id": call.call_id})

        if offenders:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "render-ui was called when it should not have been", "offenders": offenders},
            )
        return Score(
            name=self._name(),
            score=1.0,
            metadata={"scope": "any render-ui" if target_set is None else sorted(target_set)},
        )


# Mirrors ``UI_APP_RENDER_NOTE`` in ``services/mcp/src/lib/build-tool-result.ts``: the MCP server appends it to a
# query result when the client already displays that result's UI app inline.
INLINE_VIEW_NOTE = "already sees this result as an interactive view"

# A Markdown link alone in its paragraph, which PostHog Desktop draws as a full-size chart card.
# The URL runs to the closing parenthesis because SQL in ``open_query`` keeps unencoded ``(`` and ``)``.
_CHART_LINK_RE = re.compile(r'^\[[^\]]+\]\((https?://\S+?)(?:\s+"[^"]*")?\)$')
# A block-display object tag alone in its paragraph, the other chart syntax in
# ``products/desktop/packages/ui/src/utils/remarkObjectTags.ts``. A tag inside a sentence renders as a chip.
_CHART_TAG_RE = re.compile(r"^<(insight|hogql)\b([^>]*?)/?>(.*?)(?:</\1>)?$", re.IGNORECASE | re.DOTALL)
_TAG_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
_CODE_FENCE_RE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.MULTILINE | re.DOTALL)
_PROJECT_URL_RE = re.compile(r"/project/(\d+)/")


def assistant_text(output: dict | None) -> str:
    """All text the agent wrote to the user, across every assistant message.

    ``last_message`` is only the final text block, which is often a closing line written after
    a follow-up tool call, so presentation checks read the whole conversation instead.
    """
    texts: list[str] = []
    for message in (output or {}).get("messages") or []:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.extend(
                block["text"]
                for block in content
                if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
            )
    if not texts:
        last_message = (output or {}).get("last_message")
        if isinstance(last_message, str):
            texts.append(last_message)
    return "\n\n".join(text for text in texts if text)


def tool_output_text(output: str) -> str:
    """The text a tool returned, without the MCP content blocks that the log keeps around it."""
    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        return output
    if isinstance(payload, dict):
        payload = payload.get("content")
    if not isinstance(payload, list):
        return output
    texts = [
        block["text"]
        for block in payload
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    ]
    return "\n".join(texts) if texts else output


def _query_node_kind(node: object) -> str | None:
    """``sql`` for a ``HogQLQuery`` at any wrapper depth, ``insight`` for any other query kind."""
    for _ in range(3):
        if not isinstance(node, dict):
            return None
        kind = node.get("kind")
        if kind == "HogQLQuery":
            return "sql"
        if not isinstance(node.get("source"), dict):
            return "insight" if isinstance(kind, str) and kind else None
        node = node["source"]
    return None


def _collect_saved_insight_kinds(node: object, kinds: dict[str, str]) -> None:
    if isinstance(node, dict):
        short_id = node.get("short_id")
        kind = _query_node_kind(node.get("query"))
        if isinstance(short_id, str) and short_id and kind is not None:
            kinds[short_id] = kind
        for value in node.values():
            _collect_saved_insight_kinds(value, kinds)
    elif isinstance(node, list):
        for value in node:
            _collect_saved_insight_kinds(value, kinds)


# Both match JSON and the TOON text that exec returns in its default output format.
_SHORT_ID_RE = re.compile(r"""(?:\bshort_id["']?\s*:\s*["']?|/insights/)(\w+)""")
_QUERY_KIND_RE = re.compile(r"""\bkind["']?\s*:\s*["']?(\w+)""")


def saved_insight_kinds(calls: list[ToolCall]) -> dict[str, str]:
    """The query kind (``insight`` or ``sql``) of each saved insight whose query a tool call showed.

    A saved insight can hold a ``HogQLQuery``, so its link alone does not tell a typed chart from a
    SQL chart. JSON output is read exactly. Text output is read only when it names one insight.
    """
    kinds: dict[str, str] = {}
    for call in calls:
        if call.is_error:
            continue
        text = tool_output_text(call.output)
        try:
            _collect_saved_insight_kinds(json.loads(text), kinds)
        except (TypeError, ValueError):
            pass
        short_ids = set(_SHORT_ID_RE.findall(text)) - {"new"}
        if len(short_ids) != 1 or next(iter(short_ids)) in kinds:
            continue
        query = call.input.get("query")
        query_kinds = set(_QUERY_KIND_RE.findall(text + (json.dumps(query) if isinstance(query, dict) else "")))
        if "HogQLQuery" in query_kinds:
            kinds[next(iter(short_ids))] = "sql"
        elif any(kind.endswith("Query") for kind in query_kinds):
            kinds[next(iter(short_ids))] = "insight"
    return kinds


def _chart_tag_kind(paragraph: str, insight_kinds: Mapping[str, str]) -> str | None:
    match = _CHART_TAG_RE.match(paragraph)
    if match is None:
        return None
    tag, attrs, body = match.group(1).lower(), dict(_TAG_ATTR_RE.findall(match.group(2))), match.group(3).strip()
    if attrs.get("display") != "block":
        return None
    if tag == "insight":
        short_id = attrs.get("id")
        return insight_kinds.get(short_id, "saved") if short_id else None
    return "sql" if body else None


def chart_references(
    text: str, project_ids: frozenset[str] = frozenset(), insight_kinds: Mapping[str, str] | None = None
) -> list[str]:
    """Kinds of the full-size charts in ``text``, in order.

    ``insight`` is a typed query, ``sql`` is a SQL query, and ``saved`` is a saved insight that is
    not in ``insight_kinds``, so its query kind is unknown. Only a paragraph that holds nothing but a
    chart link or a block tag counts, and code blocks are skipped, because Desktop draws nothing else
    as a chart card. When ``project_ids`` is not empty, a link to any other project is skipped.
    """
    insight_kinds = insight_kinds or {}
    kinds: list[str] = []
    for paragraph in re.split(r"\n\s*\n", _CODE_FENCE_RE.sub("", text)):
        paragraph = paragraph.strip()
        match = _CHART_LINK_RE.match(paragraph)
        if match is None:
            tag_kind = _chart_tag_kind(paragraph, insight_kinds)
            if tag_kind is not None:
                kinds.append(tag_kind)
            continue
        link_kind = _chart_link_kind(match.group(1), project_ids, insight_kinds)
        if link_kind is not None:
            kinds.append(link_kind)
    return kinds


def _hogql_from_query_node(raw: str) -> str | None:
    try:
        node = json.loads(raw)
    except ValueError:
        return None
    for _ in range(3):
        if not isinstance(node, dict):
            return None
        if node.get("kind") == "HogQLQuery" and isinstance(node.get("query"), str):
            return node["query"]
        node = node.get("source")
    return None


def _chart_link_kind(url: str, project_ids: frozenset[str], insight_kinds: Mapping[str, str]) -> str | None:
    """Mirror ``parsePostHogObjectUrl`` in ``products/desktop/packages/core/src/posthog-objects/objectUrls.ts``.

    A saved insight (``/insights/<id>``, ``/i/<id>``) takes its kind from ``insight_kinds``. ``/sql?open_query=`` and an
    ``/insights/new#q=`` link that holds a ``HogQLQuery`` are SQL charts; an unsaved typed query is no
    chart. Desktop also requires the app host, which the eval cannot know because the agent's links
    and the tool results use different hosts, so only the project is checked.
    """
    parts = urlsplit(url)
    segments = [segment for segment in parts.path.split("/") if segment]
    if segments[:1] == ["project"]:
        if len(segments) < 2 or (project_ids and segments[1] not in project_ids):
            return None
        segments = segments[2:]
    if segments == ["sql"]:
        query = parse_qs(parts.query).get("open_query", [""])[0].strip()
        if query.startswith("{"):
            query = (_hogql_from_query_node(query) or "").strip()
        return "sql" if query else None
    if segments == ["insights", "new"]:
        node = parse_qs(parts.fragment).get("q", [""])[0]
        return "sql" if (_hogql_from_query_node(node) or "").strip() else None
    if len(segments) >= 2 and segments[0] in ("insights", "i") and segments[1] != "new":
        return insight_kinds.get(segments[1], "saved")
    return None


# Inputs the exec wrapper accepts that are not part of the query, so a render that leaves them out still matches.
_NON_QUERY_INPUT_KEYS = frozenset({"output_format"})


def _query_input(call: ToolCall) -> dict:
    return {key: value for key, value in call.input.items() if key not in _NON_QUERY_INPUT_KEYS}


def _render_matches_query(render: ToolCall, calls: list[ToolCall]) -> bool:
    """True when a ``render-ui`` call passes the input of a successful call to the same query tool.

    ``render-ui`` succeeds for any input because it only emits a render directive, and the chart then
    fetches its own data. An empty or invented input therefore shows an error, not a chart.
    """
    tool_name = _rendered_tool_name(render)
    tool_input = render.input.get("tool_input")
    if not isinstance(tool_input, dict) or not tool_input:
        return False
    rendered = {key: value for key, value in tool_input.items() if key not in _NON_QUERY_INPUT_KEYS}
    return any(
        not call.is_error and call.name == tool_name and _query_input(call) == rendered
        for call in calls
        if call.position < render.position
    )


def _chart_paths(output: dict | None, parser: LogParser, tools: set[str]) -> list[str]:
    """How the user saw a chart: ``render-ui``, ``inline`` (the client's UI app), or a ``chart_references`` kind."""
    paths: list[str] = []
    calls = parser.get_tool_calls()
    for call in _render_ui_calls(parser):
        if not call.is_error and _rendered_tool_name(call) in tools and _render_matches_query(call, calls):
            paths.append("render-ui")
    for call in calls:
        if not call.is_error and call.name in tools and INLINE_VIEW_NOTE in call.output:
            paths.append("inline")
    project_ids = frozenset(match for call in calls for match in _PROJECT_URL_RE.findall(call.output))
    paths.extend(chart_references(assistant_text(output), project_ids, saved_insight_kinds(calls)))
    return paths


def _chart_tools(expected: dict | None, scorer_name: str) -> set[str] | None:
    spec = _read_spec(expected, scorer_name)
    if spec is None:
        return None
    allowed = spec.get("tool_name_any_of")
    return {t for t in allowed if isinstance(t, str) and t} if isinstance(allowed, list) else set()


class ChartShown(Scorer):
    """Binary: did the user get the analytics result as a chart?

    ``expected = {"chart_shown": {"tool_name_any_of": ["query-trends"]}}``

    Any chart path counts: ``render-ui`` with a listed query tool, a listed query tool result
    that the client already displays inline (``INLINE_VIEW_NOTE``), or a full-size chart link or
    block tag in the answer (a saved insight or a SQL query). ``ChartFromTypedQuery``
    grades which of these the agent chose. ``None`` if the spec is absent.
    """

    def _name(self) -> str:
        return "chart_shown"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        tools = _chart_tools(expected, self._name())
        if tools is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        paths = _chart_paths(output, parser, tools)
        if paths:
            return Score(name=self._name(), score=1.0, metadata={"paths": paths})
        return Score(
            name=self._name(),
            score=0.0,
            metadata={"reason": "No chart was shown for the expected query tools", "expected_any_of": sorted(tools)},
        )


class ChartFromTypedQuery(Scorer):
    """Binary: when a chart was shown, did it come from the typed query rather than rewritten SQL?

    ``expected = {"chart_from_typed_query": {"tool_name_any_of": ["query-trends"]}}``

    An agent that answers with ``query-trends`` and then links a hand-written SQL chart shows
    numbers computed by a different query, without PostHog's standard definitions such as the
    project timezone or test-account filtering. Score 1.0 when any chart comes from
    ``render-ui``, the inline view, or a saved insight that holds a typed query; 0.0 when every
    chart is a SQL query. ``None`` when no chart was shown (graded by ``ChartShown``), when the only
    other charts are saved insights whose query kind no tool call showed, or the spec is absent.
    """

    def _name(self) -> str:
        return "chart_from_typed_query"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        tools = _chart_tools(expected, self._name())
        if tools is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        parser = _build_parser(output)
        if parser is None:
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        paths = _chart_paths(output, parser, tools)
        if not paths:
            return Score(name=self._name(), score=None, metadata={"reason": "No chart was shown"})
        if any(path not in ("sql", "saved") for path in paths):
            return Score(name=self._name(), score=1.0, metadata={"paths": paths})
        if "saved" in paths:
            return Score(
                name=self._name(),
                score=None,
                metadata={"paths": paths, "reason": "No tool call showed the query of the linked saved insight"},
            )
        return Score(name=self._name(), score=0.0, metadata={"paths": paths})


_TABLE_SEPARATOR_RE = re.compile(r"^(?=.*\|)\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def markdown_table_row_counts(text: str) -> list[int]:
    """Count the data rows of each Markdown table in ``text``, in order."""
    lines = text.splitlines()
    counts: list[int] = []
    index = 1
    while index < len(lines):
        if "|" in lines[index - 1] and _TABLE_SEPARATOR_RE.match(lines[index]):
            rows = 0
            index += 1
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows += 1
                index += 1
            counts.append(rows)
        index += 1
    return counts


class NoMarkdownDataTable(Scorer):
    """Binary: did the agent avoid restating the query result as a Markdown table?

    ``expected = {"no_markdown_data_table": {}}`` or ``{"no_markdown_data_table": {"max_rows": 3}}``

    A chart already shows the series, so a table that retypes it adds length and hides
    the conclusion. Small summary tables (at most ``max_rows`` data rows, default 3, such as
    this period against the previous one) still pass. Score 0.0 when any table in the agent's
    messages is longer. ``None`` if the spec is absent or the agent wrote no text.
    """

    DEFAULT_MAX_ROWS = 3

    def _name(self) -> str:
        return "no_markdown_data_table"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        spec = _read_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})

        text = assistant_text(output)
        if not text.strip():
            return Score(name=self._name(), score=None, metadata={"reason": "No agent text"})

        max_rows = spec.get("max_rows", self.DEFAULT_MAX_ROWS)
        row_counts = markdown_table_row_counts(text)
        too_long = [rows for rows in row_counts if rows > max_rows]
        return Score(
            name=self._name(),
            score=0.0 if too_long else 1.0,
            metadata={"table_row_counts": row_counts, "max_rows": max_rows},
        )


class _TableSources(TraversingVisitor):
    def __init__(self) -> None:
        self.tables: list[str] = []
        self.ctes: set[str] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.ctes.update(name.lower() for name in node.ctes or {})
        super().visit_select_query(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field):
            self.tables.append(".".join(str(part) for part in node.table.chain).lower())
        super().visit_join_expr(node)


def is_catalog_sql(call: ToolCall) -> bool:
    """True when an ``execute-sql`` call reads only PostHog entity tables (``system.*``).

    Catalog lookups, such as checking for a saved insight or an action, are justified SQL
    under the routing rules, so they never count as an analytics query. A query that the
    HogQL parser cannot read counts as analytics SQL.
    """
    query = call.input.get("query")
    if not isinstance(query, str):
        return False
    try:
        sources = _TableSources()
        sources.visit(parse_select(query))
    except BaseHogQLError:
        return False
    tables = [table for table in sources.tables if table not in sources.ctes]
    return bool(tables) and all(table.startswith("system.") for table in tables)
