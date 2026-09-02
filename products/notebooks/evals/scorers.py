"""Scorers for the notebook evals.

``NotebookCreated`` and ``CellRunsCompleted`` grade the notebook the agent left behind,
not the transcript that describes it. A cell run that is dispatched and one that finishes
look nearly identical in the log — the tool returns ``status: running`` either way — and it
is the finished run whose result the notebook renders, so the run rows are the honest source.

Reading the ORM means running async: the engine dispatches every scorer through
``eval_async``, and the base class's sync branch would execute Django ORM calls on the
event loop, which Django's async-safety guard rejects.

``NotebookApproachQuality`` is the qualitative layer. It reads the cells the agent authored
from the tool-call transcript rather than the database, because the question it asks is about
the *approach* the agent took — the SQL it wrote, the Python it wrote, the story it told —
which is exactly what the ``notebooks-add-cell`` calls carry. Whether those cells actually
ran is a different question, and ``CellRunsCompleted`` already answers it from the run rows.
"""

from __future__ import annotations

import asyncio
from typing import Any

from products.notebooks.backend.markdown_conversion import MARKDOWN_NOTEBOOK_NODE_TYPE
from products.notebooks.backend.models import Notebook, NotebookNodeRun
from products.posthog_ai.eval_harness.log_parser import LogParser, ToolCall
from products.posthog_ai.eval_harness.scorers import (
    GRADED_ALIGNMENT_CHOICE_SCORES,
    JUDGE_MODEL,
    AsyncOnlyScorerMixin,
    JudgedScorer,
)
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

__all__ = ["CellRunsCompleted", "NotebookApproachQuality", "NotebookCreated"]


def _seeded_team_id(output: dict | None) -> int | None:
    seed = (output or {}).get("seed")
    team_id = seed.get("team_id") if isinstance(seed, dict) else None
    return team_id if isinstance(team_id, int) else None


def _spec(expected: dict | None, name: str) -> dict | None:
    if not isinstance(expected, dict):
        return None
    spec = expected.get(name)
    return spec if isinstance(spec, dict) else None


def _markdown_body(content: Any) -> str | None:
    """The markdown of a ``ph-markdown-notebook`` document, or None for legacy rich text."""
    if not isinstance(content, dict):
        return None
    nodes = content.get("content")
    if not isinstance(nodes, list) or not nodes:
        return None
    first = nodes[0]
    if not isinstance(first, dict) or first.get("type") != MARKDOWN_NOTEBOOK_NODE_TYPE:
        return None
    attrs = first.get("attrs")
    if not isinstance(attrs, dict):
        return None
    markdown = attrs.get("markdown")
    return markdown if isinstance(markdown, str) and markdown else None


class NotebookCreated(AsyncOnlyScorerMixin, Scorer):
    """Binary: does the case's team hold a markdown notebook the agent created?

    Opt in with ``expected = {"notebook_created": {}}``.

    Markdown is what the whole new flow produces, so a notebook that came back as
    legacy rich text (``markdown`` unset on its single document node) fails rather
    than counting — that is the clobbering regression, not a near miss.
    """

    def _name(self) -> str:
        return "notebook_created"

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        if _spec(expected, self._name()) is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} key on case"})
        team_id = _seeded_team_id(output)
        if team_id is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No seed.team_id — case needs a seeder"})

        notebooks = await asyncio.to_thread(self._read_notebooks, team_id)
        if not notebooks:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No notebook in the team"})
        markdown = [n for n in notebooks if n["is_markdown"]]
        if not markdown:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={"reason": "Notebook exists but is not a markdown document", "notebooks": notebooks},
            )
        return Score(name=self._name(), score=1.0, metadata={"notebooks": markdown})

    @staticmethod
    def _read_notebooks(team_id: int) -> list[dict[str, Any]]:
        return [
            {
                "short_id": notebook.short_id,
                "title": notebook.title,
                "is_markdown": _markdown_body(notebook.content) is not None,
            }
            for notebook in Notebook.objects.filter(team_id=team_id, deleted=False)
        ]


class CellRunsCompleted(AsyncOnlyScorerMixin, Scorer):
    """Binary: did every required kind of cell reach a completed run?

    ``expected = {"cell_runs_completed": {"node_types": ["hogql", "python"]}}``

    ``hogql`` runs take the direct lane and never touch a sandbox; ``python`` and
    ``duckdb`` runs go out to the notebook kernel. Naming both is what separates "the
    agent wrote a python cell" from "the kernel actually ran it", and the observed
    statuses land in the metadata so a failure says which of the two happened.
    """

    def _name(self) -> str:
        return "cell_runs_completed"

    async def _run_eval_async(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": f"No {self._name()} spec on case"})
        required = [t for t in spec.get("node_types", []) if isinstance(t, str) and t]
        if not required:
            return Score(name=self._name(), score=None, metadata={"reason": "Missing 'node_types' on spec"})
        team_id = _seeded_team_id(output)
        if team_id is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No seed.team_id — case needs a seeder"})

        runs = await asyncio.to_thread(self._read_runs, team_id)
        completed = {run["node_type"] for run in runs if run["status"] == NotebookNodeRun.Status.DONE}
        missing = [node_type for node_type in required if node_type not in completed]
        if missing:
            return Score(
                name=self._name(),
                score=0.0,
                metadata={
                    "reason": "No completed run for every required cell type",
                    "missing_node_types": missing,
                    "runs": runs,
                },
            )
        return Score(name=self._name(), score=1.0, metadata={"runs": runs})

    @staticmethod
    def _read_runs(team_id: int) -> list[dict[str, Any]]:
        return [
            {"node_type": node_type, "status": status, "error": error}
            for node_type, status, error in NotebookNodeRun.objects.for_team(team_id)
            .order_by("created_at")
            .values_list("node_type", "status", "error")
        ]


_ADD_CELL_TOOL = "notebooks-add-cell"


def _parser_for(output: dict | None) -> LogParser | None:
    if not output:
        return None
    raw_log = output.get("raw_log")
    if not raw_log:
        return None
    return LogParser.cached(raw_log, initial_prompt=output.get("prompt", "") or "")


def _final_message(output: dict | None) -> str:
    message = (output or {}).get("last_message") or ""
    return message if isinstance(message, str) else str(message)


def _authored_cells(parser: LogParser) -> list[ToolCall]:
    """Every cell the agent successfully added, in the order it added them.

    Grades what the agent authored, so a rejected call (``is_error``) is left out —
    the recovery is graded by whether a later, successful call took its place.
    """
    calls = [c for c in parser.get_tool_calls(_ADD_CELL_TOOL) if not c.is_error]
    return sorted(calls, key=lambda c: c.position)


def _render_cells(cells: list[ToolCall]) -> str:
    """Render the authored cells as a readable notebook outline for the judge."""
    blocks: list[str] = []
    for index, call in enumerate(cells, start=1):
        payload = call.input if isinstance(call.input, dict) else {}
        cell_type = payload.get("cell_type") or "?"
        title = payload.get("title")
        header = f"Cell {index} [{cell_type}]" + (f" — {title}" if title else "")
        body = payload.get("code") or payload.get("markdown") or "(empty)"
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)


NOTEBOOK_APPROACH_PROMPT = """
You are an expert data analyst judging whether an agent built a notebook that follows a sound
analytical approach for the user's request. You are grading the *approach*, not whether the
numbers are exactly right — a separate check confirms the cells actually ran.

The agent works in a PostHog notebook. It writes `sql` cells (HogQL against product data) and
`python` cells (pandas over the dataframes those SQL cells produce), and `markdown` cells for
prose. Judge the cells it authored, in order, against the expected approach.

Reward a notebook that:
- pulls the behavioural signals the question needs with SQL, using real events and properties,
- carries the analysis into Python over those dataframes when the question calls for it,
- explains its reasoning and lands on a conclusion a reader can act on.

Penalize a notebook that skips a step the expected approach names, hard-codes an answer instead
of deriving it from the data, or answers a different question than the one asked.

User request:
<user_request>
{{output.prompt}}
</user_request>

Expected approach:
<expected_approach>
{{expected.approach}}
</expected_approach>

Cells the agent authored, in order:
<authored_cells>
{{output.authored_cells}}
</authored_cells>

Final assistant message:
<final_message>
{{output.final_message}}
</final_message>
""".strip()


NOTEBOOK_APPROACH_RUBRIC = """
How well does the notebook's approach match the expected approach? Choose one:
- perfect: Follows every step of the expected approach — the right signals in SQL, the analysis carried into Python, a clear conclusion.
- near_perfect: Follows the expected approach with at most one immaterial gap.
- slightly_off: Mostly follows it, with a minor step done weakly or skipped.
- somewhat_misaligned: Some of the right pieces, but misses a load-bearing step (e.g. no Python analysis when the question needs it, or SQL that ignores the behavioural signals).
- strongly_misaligned: Does not follow the expected approach or answers a different question.
- useless: No meaningful analysis, or a hard-coded answer not derived from the data.
""".strip()


class NotebookApproachQuality(JudgedScorer):
    """Graded LLM judge: did the notebook follow the expected analytical approach?

    Opt in per case with ``expected = {"notebook_approach_quality": {"approach": "..."}}``,
    where ``approach`` is a plain-language rubric of what a good notebook for this prompt
    does. Reads the authored cells from the transcript, so it grades the same whether or not
    a cell's run finished; pair it with ``CellRunsCompleted`` to also require execution.

    Self-skips (``None``) when the case does not opt in. Scores ``0.0`` when it opts in but
    the agent authored no cells — a run that built nothing is a failure, not a skip.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            name="notebook_approach_quality",
            prompt_template=NOTEBOOK_APPROACH_PROMPT + "\n\n" + NOTEBOOK_APPROACH_RUBRIC,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=1024,
            **kwargs,
        )

    def _prepare(self, output: Any, expected: Any) -> dict[str, Any] | Score:
        spec = _spec(expected, self._name())
        if spec is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not requested"})
        approach = spec.get("approach")
        if not isinstance(approach, str) or not approach.strip():
            return Score(name=self._name(), score=None, metadata={"reason": "no approach rubric configured"})

        parser = _parser_for(output)
        if parser is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No raw log to read cells from"})
        cells = _authored_cells(parser)
        if not cells:
            return Score(name=self._name(), score=0.0, metadata={"reason": "Agent authored no cells"})

        prompt = parser.get_user_prompt() or (output or {}).get("prompt", "")
        return {
            "output": {
                "prompt": prompt,
                "authored_cells": _render_cells(cells),
                "final_message": _final_message(output),
            },
            "expected": {"approach": approach},
        }
