from __future__ import annotations

import re
from abc import abstractmethod

from products.posthog_ai.eval_harness.log_parser import LogParser, ToolCall
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.posthog_ai.eval_harness.scorers.deterministic import is_answer_query_tool

EXPLAIN_CHART_TOOL = "explain-chart"
NOTEBOOK_CREATE_TOOLS = frozenset({"notebooks-create", "notebooks-create-markdown"})
BRIEF_REPLY_MAX_WORDS = 150
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE)


class _AfterExplanationScorer(Scorer):
    """Grades the run around its last successful ``explain-chart`` call; skips runs without one."""

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs) -> Score:
        if not output or not output.get("raw_log"):
            return Score(name=self._name(), score=None, metadata={"reason": "No raw log"})
        parser = LogParser.cached(output["raw_log"], initial_prompt=output.get("prompt", "") or "")
        calls = [call for call in parser.get_tool_calls() if not call.is_error]
        explanations = [call for call in calls if call.name == EXPLAIN_CHART_TOOL]
        if not explanations:
            return Score(name=self._name(), score=None, metadata={"reason": "No successful explain-chart call"})
        return self._grade(parser, calls, explanations[-1])

    @abstractmethod
    def _grade(self, parser: LogParser, calls: list[ToolCall], explanation: ToolCall) -> Score: ...


class ExplainChartEndsInvestigation(_AfterExplanationScorer):
    """No query or notebook follows the chart explanation: it is the answer, not a step before one."""

    def _name(self) -> str:
        return "explain_chart_ends_investigation"

    def _grade(self, parser: LogParser, calls: list[ToolCall], explanation: ToolCall) -> Score:
        later = [
            call.name
            for call in calls[calls.index(explanation) + 1 :]
            if is_answer_query_tool(call.name) or call.name in NOTEBOOK_CREATE_TOOLS
        ]
        return Score(name=self._name(), score=0.0 if later else 1.0, metadata={"calls_after_explanation": later})


class ExplainedSavedInsight(_AfterExplanationScorer):
    """Every case names a saved insight, so the explanation should follow it by id."""

    def _name(self) -> str:
        return "explained_saved_insight"

    def _grade(self, parser: LogParser, calls: list[ToolCall], explanation: ToolCall) -> Score:
        insight_id = explanation.input.get("insightId")
        return Score(
            name=self._name(), score=1.0 if insight_id is not None else 0.0, metadata={"insightId": insight_id}
        )


class BriefReplyAfterExplanation(_AfterExplanationScorer):
    """The reply points into the explanation instead of rewriting it as a report."""

    def _name(self) -> str:
        return "brief_reply_after_explanation"

    def _grade(self, parser: LogParser, calls: list[ToolCall], explanation: ToolCall) -> Score:
        reply = parser.get_final_agent_message() or ""
        words = len(reply.split())
        has_heading = bool(_MARKDOWN_HEADING.search(reply))
        brief = words <= BRIEF_REPLY_MAX_WORDS and not has_heading
        return Score(
            name=self._name(), score=1.0 if brief else 0.0, metadata={"words": words, "has_heading": has_heading}
        )
