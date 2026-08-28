"""Scorers for the notebook evals.

These grade the notebook the agent left behind, not the transcript that describes it.
A cell run that is dispatched and one that finishes look nearly identical in the log —
the tool returns ``status: running`` either way — and it is the finished run whose
result the notebook renders, so the run rows are the honest source.

Reading the ORM means running async: the engine dispatches every scorer through
``eval_async``, and the base class's sync branch would execute Django ORM calls on the
event loop, which Django's async-safety guard rejects.
"""

from __future__ import annotations

import asyncio
from typing import Any

from products.notebooks.backend.markdown_conversion import MARKDOWN_NOTEBOOK_NODE_TYPE
from products.notebooks.backend.models import Notebook, NotebookNodeRun
from products.posthog_ai.eval_harness.scorers import AsyncOnlyScorerMixin
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer

__all__ = ["CellRunsCompleted", "NotebookCreated"]


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
