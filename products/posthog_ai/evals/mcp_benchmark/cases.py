"""Cases sourced from the MCP agent-experience benchmark.

``services/mcp/evals/benchmark/tasks.yaml`` is the single source of truth for
these tasks — its own vitest fixture tests guard it against tool-catalog drift,
so this module reads it directly rather than forking a Python copy. Loading
happens at suite import time, which makes ``--list`` the smoke check for yaml
breakage.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from products.posthog_ai.eval_harness.config import BaseEvalCase

TASKS_YAML = Path(__file__).parents[4] / "services" / "mcp" / "evals" / "benchmark" / "tasks.yaml"


class McpBenchmarkTask(BaseModel):
    """The subset of the benchmark's task schema this harness consumes."""

    id: str
    category: str
    intent: str
    expected_tools: list[str] = Field(default_factory=list)
    acceptable_tools: list[str] = Field(default_factory=list)
    success_criteria: str


def load_benchmark_tasks() -> tuple[int, list[McpBenchmarkTask]]:
    """Parse tasks.yaml into (benchmark version, tasks)."""
    data = yaml.safe_load(TASKS_YAML.read_text())
    return data["version"], [McpBenchmarkTask.model_validate(task) for task in data["tasks"]]


def load_benchmark_cases(category: str) -> list[BaseEvalCase]:
    """Translate one benchmark category into eval cases.

    ``expected_tools`` / ``acceptable_tools`` ride along in metadata: the
    one-shot port executes queries in-process rather than through the MCP
    server, so tool-selection scoring is a follow-up that needs the live tool
    catalog.
    """
    version, tasks = load_benchmark_tasks()
    cases = [
        BaseEvalCase(
            name=task.id,
            prompt=task.intent,
            expected={"success_criteria": task.success_criteria},
            metadata={
                "category": task.category,
                "benchmark_version": version,
                "expected_tools": task.expected_tools,
                "acceptable_tools": task.acceptable_tools,
            },
        )
        for task in tasks
        if task.category == category
    ]
    if not cases:
        raise ValueError(f"No MCP benchmark tasks in category {category!r} in {TASKS_YAML}")
    return cases
