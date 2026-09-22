from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.log_parser import LogParser
from products.signals.evals.agentic.datasets import EvalCase, RepoSelectionCase
from products.signals.evals.agentic.scoring import DeterministicScorer, Score


def repository_evidence_calls(raw_log: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for tool in LogParser.cached(raw_log).get_tool_calls("execute-sql"):
        query = tool.input.get("query")
        if tool.is_error or not isinstance(query, str) or "system.integration_repository_cache" not in query.lower():
            continue
        calls.append({"tool": tool.raw_name, "input": tool.input, "output": tool.output})
    return calls


class RepoSelectionCorrectnessScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("repo_selected_correct")

    def grade(self, case: EvalCase, output: Any) -> list[Score]:
        assert isinstance(case, RepoSelectionCase)
        exp = case.expected
        actual = (output.repository or None) and output.repository.strip().lower()
        if exp.expect_null:
            ok = actual is None
            return [Score.boolean(self.name, ok, reasoning=f"expected no repo, got {actual!r}")]
        raw = exp.expected_repository
        acceptable = (raw,) if isinstance(raw, str) else tuple(raw or ())
        acceptable = tuple(r.lower() for r in acceptable)
        if not acceptable:
            return [Score.errored(self.name, f"case {case.case_id!r} sets neither expected_repository nor expect_null")]
        ok = actual in acceptable
        return [Score.boolean(self.name, ok, reasoning=f"expected one of {acceptable} actual={actual!r}")]


class RepositoryEvidenceScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("repository_evidence_used")

    def grade(self, case: EvalCase, output: Any) -> list[Score]:
        calls = repository_evidence_calls(getattr(output, "raw_log", ""))
        return [Score.boolean(self.name, bool(calls), reasoning=f"cache_queries={len(calls)}")]


def default_repo_selection_scorers() -> tuple[Any, ...]:
    return (RepoSelectionCorrectnessScorer(), RepositoryEvidenceScorer())
