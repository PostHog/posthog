"""Scorers for the inbox consumer evals.

Every scorer opts in through its own key in the case's ``expected`` and skips the cases that leave it out.
A case names a seeded report by its ``InboxReport.key``. The scorers resolve it to the report's id for the
case's project through ``output["seed"]``.
"""

from __future__ import annotations

import re
import json
from datetime import datetime
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.data_catalog.evals.scorers import final_answer
from products.posthog_ai.eval_harness.log_parser import EXECUTE_SQL_TOOL_NAME, ToolCall
from products.posthog_ai.eval_harness.scorers import (
    BINARY_CHOICE_SCORES,
    JudgedScorer,
    expected_spec,
    parser_for,
    reads_table,
)
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

INBOX_LIST_TOOL = "inbox-reports-list"
INBOX_RETRIEVE_TOOL = "inbox-reports-retrieve"
INBOX_SEARCH_TOOL = "inbox-reports-search"
INBOX_CLAIM_TOOL = "inbox-reports-claim"
INBOX_FOR_ME_TOOL = "inbox-reports-for-me"
INBOX_READ_TOOLS = frozenset({INBOX_LIST_TOOL, INBOX_RETRIEVE_TOOL, INBOX_SEARCH_TOOL, INBOX_FOR_ME_TOOL})
POSTHOG_MCP_SERVER = "posthog"
INBOX_TABLES = ("inbox_reports", "system.inbox_reports")
INBOX_JUDGE_MODEL = "gpt-6.2-sol"

_PULL_REQUEST_COMMAND = re.compile(r"\bgh\s+pr\s+(?:create|edit)\b")
_WRITTEN_FILE_KEYS = ("file_path", "path")


@frozen
class SeededReport:
    id: str
    title: str


def seeded_report(output: dict[str, Any] | None, key: str) -> SeededReport | None:
    report = ((output or {}).get("seed") or {}).get("reports", {}).get(key)
    return SeededReport(id=report["id"], title=report["title"]) if report else None


def _query(call: ToolCall) -> str:
    query = call.input.get("query")
    return query if isinstance(query, str) else ""


def _report_id(call: ToolCall) -> str:
    return str(call.input.get("id") or call.input.get("report_id") or "")


def reads_inbox(call: ToolCall) -> bool:
    """A successful read of the inbox: one of its read tools, or SQL over the inbox reports table."""
    if call.is_error:
        return False
    return call.name in INBOX_READ_TOOLS or (
        call.name == EXECUTE_SQL_TOOL_NAME and reads_table(_query(call), INBOX_TABLES)
    )


def searches_inbox(call: ToolCall) -> bool:
    """A successful search of the inbox: the search tool, the list's text filter, or SQL over the table."""
    if call.is_error:
        return False
    if call.name == INBOX_LIST_TOOL:
        return bool(call.input.get("search"))
    return call.name == INBOX_SEARCH_TOOL or (
        call.name == EXECUTE_SQL_TOOL_NAME and reads_table(_query(call), INBOX_TABLES)
    )


def returns_report(call: ToolCall, report: SeededReport) -> bool:
    if call.name == INBOX_RETRIEVE_TOOL:
        return _report_id(call) == report.id
    return report.id in call.output or report.title in call.output


def claims_report(call: ToolCall, report: SeededReport) -> bool:
    return (
        call.name == INBOX_CLAIM_TOOL
        and not call.is_error
        and _report_id(call) == report.id
        and call.input.get("release") is not True
    )


def _input_text(call: ToolCall) -> str:
    return json.dumps(call.input, default=str)


def pull_request_text(calls: list[ToolCall]) -> str:
    """What the agent wrote into its pull request: the `gh pr` commands and the files they pass as a body.

    Failed commands count, because a sandbox without push access still shows the description the agent
    meant to publish.
    """
    commands = [_input_text(call) for call in calls if _PULL_REQUEST_COMMAND.search(_input_text(call))]
    if not commands:
        return ""
    body_files = [
        _input_text(call)
        for call in calls
        if any(
            isinstance(call.input.get(key), str) and call.input[key] and call.input[key] in command
            for key in _WRITTEN_FILE_KEYS
            for command in commands
        )
    ]
    return "\n".join([*commands, *body_files])


def _spec(output: dict[str, Any] | None, expected: dict | None, name: str) -> dict[str, Any] | Score:
    """The scorer's entry in ``expected``, or the skip score for a case that does not ask for the scorer."""
    spec = expected_spec(expected, name)
    if spec is None:
        return Score(name=name, score=None, metadata={"reason": "Not requested by this case"})
    if parser_for(output) is None:
        return Score(name=name, score=0.0, metadata={"reason": "No agent log"})
    return spec


def _calls(output: dict[str, Any] | None) -> list[ToolCall]:
    parser = parser_for(output)
    return parser.get_tool_calls() if parser else []


def _report_for(output: dict[str, Any] | None, spec: dict[str, Any], name: str) -> SeededReport | Score:
    report = seeded_report(output, spec["report"])
    if report is None:
        return Score(name=name, score=0.0, metadata={"reason": f"Report {spec['report']!r} was not seeded"})
    return report


def _binary(name: str, passed: bool, **metadata: Any) -> Score:
    return Score(name=name, score=1.0 if passed else 0.0, metadata=metadata)


class InboxRead(Scorer):
    """Did the agent read the inbox at all? Opts in via ``expected={"inbox_read": {}}``."""

    def _name(self) -> str:
        return "inbox_read"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(output, expected, self._name())
        if isinstance(spec, Score):
            return spec
        tools = sorted({call.name for call in _calls(output) if reads_inbox(call)})
        return _binary(self._name(), bool(tools), inbox_tools=tools)


class InboxSqlRan(Scorer):
    """Did a SQL query read the inbox reports table? Opts in via ``expected={"inbox_sql_ran": {}}``."""

    def _name(self) -> str:
        return "inbox_sql_ran"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(output, expected, self._name())
        if isinstance(spec, Score):
            return spec
        ran = any(call.name == EXECUTE_SQL_TOOL_NAME and reads_inbox(call) for call in _calls(output))
        return _binary(self._name(), ran)


class _ReportScorer(Scorer):
    """Base for a scorer about one seeded report. Opts in via ``expected={<name>: {"report": <key>}}``."""

    name: str

    def _name(self) -> str:
        return self.name

    def _passes(self, output: dict[str, Any], calls: list[ToolCall], report: SeededReport) -> tuple[bool, dict]:
        raise NotImplementedError

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(output, expected, self._name())
        if isinstance(spec, Score):
            return spec
        report = _report_for(output, spec, self._name())
        if isinstance(report, Score):
            return report
        passed, metadata = self._passes(output or {}, _calls(output), report)
        return _binary(self._name(), passed, report=spec["report"], **metadata)


class ReportPulled(_ReportScorer):
    """Did an inbox read return the report?"""

    name = "report_pulled"

    def _passes(self, output: dict[str, Any], calls: list[ToolCall], report: SeededReport) -> tuple[bool, dict]:
        tools = sorted({call.name for call in calls if reads_inbox(call) and returns_report(call, report)})
        return bool(tools), {"returned_by": tools}


class FoundThroughSearchOrSql(_ReportScorer):
    """Did a search or a SQL query return the report? Paging through the list does not count."""

    name = "found_through_search_or_sql"

    def _passes(self, output: dict[str, Any], calls: list[ToolCall], report: SeededReport) -> tuple[bool, dict]:
        tools = sorted({call.name for call in calls if searches_inbox(call) and returns_report(call, report)})
        return bool(tools), {"returned_by": tools}


class ReportClaimed(_ReportScorer):
    """Did the agent claim the report before or while it worked on it?"""

    name = "report_claimed"

    def _passes(self, output: dict[str, Any], calls: list[ToolCall], report: SeededReport) -> tuple[bool, dict]:
        return any(claims_report(call, report) for call in calls), {}


BudgetMetric = Literal["tool_calls", "tool_output_chars", "tool_seconds"]


def _timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def measure(calls: list[ToolCall], metric: BudgetMetric) -> float | None:
    """The run's cost in one unit. Seconds run from the first tool call's start to the last one's end."""
    if metric == "tool_calls":
        return float(len(calls))
    if metric == "tool_output_chars":
        return float(sum(len(call.output) for call in calls))
    started = [moment for call in calls if (moment := _timestamp(call.started_at))]
    ended = [moment for call in calls if (moment := _timestamp(call.ended_at))]
    if not started or not ended:
        return None
    return (max(ended) - min(started)).total_seconds()


class WithinBudget(Scorer):
    """Did the run stay within a budget? Opts in via ``expected={"<metric>_within_budget": {"max": <number>}}``.

    Tool output characters stand in for the tokens the reads cost, and tool seconds for their latency.
    Only calls to the PostHog MCP server count. The agent's own tools and the sandbox's tools cost the same in
    every run, so counting them would measure the harness and not the inbox.
    """

    def __init__(self, metric: BudgetMetric):
        self.metric: BudgetMetric = metric

    def _name(self) -> str:
        return f"{self.metric}_within_budget"

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs: Any) -> Score:
        spec = _spec(output, expected, self._name())
        if isinstance(spec, Score):
            return spec
        value = measure([call for call in _calls(output) if call.server == POSTHOG_MCP_SERVER], self.metric)
        if value is None:
            return Score(name=self._name(), score=None, metadata={"reason": "The log has no tool call times"})
        return _binary(self._name(), value <= spec["max"], value=value, max=spec["max"])


def _final_answer(output: dict[str, Any] | None, name: str) -> str | Score:
    # The answer can come before a `show_actions` button, and the last message is then only a note about it.
    answer = final_answer(output)
    if not answer:
        return Score(name=name, score=0.0, metadata={"reason": "No final message"})
    return answer


class _BinaryJudge(JudgedScorer):
    """Base for a judge that answers `yes` or `no`."""

    def __init__(self, *, name: str, prompt_template: str, **kwargs: Any):
        super().__init__(
            name=name,
            prompt_template=prompt_template.strip(),
            choice_scores=BINARY_CHOICE_SCORES,
            model=INBOX_JUDGE_MODEL,
            max_completion_tokens=256,
            **kwargs,
        )


class _AnswerJudge(_BinaryJudge):
    """Base for a judge of the agent's final answer. Opts in via ``expected={<name>: {...}}``."""

    def _expected(self, spec: dict[str, Any]) -> dict[str, Any] | None:
        """The template's `expected` variables, taken from the case's entry. None when the template needs none."""
        return None

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        spec = expected_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Not requested by this case"})
        answer = _final_answer(output, self._name())
        if isinstance(answer, Score):
            return answer
        prepared: dict[str, Any] = {"output": {"prompt": output.get("prompt", ""), "last_message": answer}}
        if (variables := self._expected(spec)) is not None:
            prepared["expected"] = variables
        return prepared


class AnswerStatesFact(_AnswerJudge):
    """Does the final answer convey a fact? Opts in via ``expected={"answer_states_fact": {"fact": "..."}}``."""

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="answer_states_fact",
            prompt_template="""
You are checking an answer that an assistant gave to a user of a product analytics tool.

The user asked:
<prompt>
{{output.prompt}}
</prompt>

The assistant answered:
<final_answer>
{{output.last_message}}
</final_answer>

The answer should convey this, which PostHog's own records state:
<fact>
{{expected.fact}}
</fact>

Does the answer convey that fact? Different wording is fine. It also counts when the answer gives the fact as what a report or record says and then questions it. It does not count when any part of the fact is missing or stated wrongly. Answer `yes` or `no`.
""",
            **kwargs,
        )

    def _expected(self, spec: dict[str, Any]) -> dict[str, Any] | None:
        return {"fact": spec["fact"]}


class AnswerSurfacesReports(_AnswerJudge):
    """Does the final answer tell the user about the reports that wait for them?

    Opts in via ``expected={"answer_surfaces_reports": {"reports": [<title>, ...]}}``.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="answer_surfaces_reports",
            prompt_template="""
You are checking an answer that an assistant gave to a user who asked what is going on in their product.

The user asked:
<prompt>
{{output.prompt}}
</prompt>

The assistant answered:
<final_answer>
{{output.last_message}}
</final_answer>

PostHog had already researched these findings for this user:
<findings>
{{expected.reports}}
</findings>

Does the answer tell the user about at least two of these findings? A finding counts when the answer describes the same problem, in any wording. Answer `yes` or `no`.
""",
            **kwargs,
        )

    def _expected(self, spec: dict[str, Any]) -> dict[str, Any] | None:
        return {"reports": "\n".join(f"- {title}" for title in spec["reports"])}


def pull_request_draft(output: dict[str, Any] | None) -> str:
    """The pull request the agent opened or drafted: its `gh pr` commands, then its last message.

    Eval runs cannot publish, so a case asks for the title and description in the answer instead.
    """
    parts = []
    if commands := pull_request_text(_calls(output)):
        parts.append(f"The agent's `gh pr` commands and the files they read:\n{commands}")
    if answer := final_answer(output):
        parts.append(f"The agent's last message:\n{answer}")
    return "\n\n".join(parts)


_PULL_REQUEST_JUDGE_INTRO = """
You are checking a pull request that an agent opened or drafted to fix a problem found by PostHog's Self-driving inbox.

<pull_request>
{{output.pull_request}}
</pull_request>

Only the pull request's description counts. A link elsewhere in the agent's message, outside the title and description it drafted, does not.
""".strip()


class _PullRequestJudge(_BinaryJudge):
    """Base for a judge of the pull request description. Opts in via ``expected={<name>: {"report": <key>}}``."""

    def __init__(self, *, name: str, question: str, **kwargs: Any):
        super().__init__(
            name=name, prompt_template=f"{_PULL_REQUEST_JUDGE_INTRO}\n\n{question} Answer `yes` or `no`.", **kwargs
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        spec = expected_spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "Not requested by this case"})
        report = seeded_report(output, spec["report"])
        if report is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"Report {spec['report']!r} was not seeded"})
        draft = pull_request_draft(output)
        if not draft:
            return Score(name=self._name(), score=0.0, metadata={"reason": "The agent drafted no pull request"})
        return {"output": {"pull_request": draft}, "expected": {"report_id": report.id}}


class PullRequestLinksReport(_PullRequestJudge):
    """Does the pull request description link the inbox report?"""

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="pull_request_links_report",
            question=(
                "The inbox report has the id {{expected.report_id}}. "
                "Does the pull request description link to that report, with a URL that holds the id?"
            ),
            **kwargs,
        )


class PullRequestFramesReport(_PullRequestJudge):
    """Does the pull request description present the link as the Self-driving report with the evidence?"""

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="pull_request_frames_report",
            question=(
                "Does the description link to the inbox report and say that the link is the Self-driving report "
                'that holds the evidence for the change? A line such as "Self-driving report with evidence: <link>" '
                'qualifies. A bare link, or a link called only "context" or "report", does not.'
            ),
            **kwargs,
        )


class AutomationProposed(_AnswerJudge):
    """Does the final answer propose an automation that implements inbox reports?

    Opts in via ``expected={"automation_proposed": {}}``.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(
            name="automation_proposed",
            prompt_template="""
You are checking the last message of an assistant that worked with a user on reports from PostHog's Self-driving inbox.

The user asked:
<prompt>
{{output.prompt}}
</prompt>

The assistant's last message:
<final_answer>
{{output.last_message}}
</final_answer>

Does the message propose to set up an automation that keeps checking the Self-driving inbox and implements its reports without the user asking each time? A scheduled or recurring agent run qualifies. An offer to fix another report now, or to check the inbox again on request, does not. Answer `yes` or `no`.
""",
            **kwargs,
        )
