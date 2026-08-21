from __future__ import annotations

from typing import Any

from products.posthog_ai.eval_harness.acp_log import parse_log
from products.signals.evals.agentic.datasets import EvalCase, RepoSelectionCase
from products.signals.evals.agentic.scoring import DeterministicScorer, Score


def repository_evidence_calls(raw_log: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for tool in parse_log(raw_log).tools:
        command = " ".join(str(value) for value in tool.input.values())
        normalized = command.lower()
        tool_name = tool.name.lower().replace("_", "-")
        is_posthog_query = "posthog" in tool_name and ("exec" in tool_name or "execute-sql" in tool_name)
        if (
            tool.is_error
            or not is_posthog_query
            or "execute-sql" not in normalized
            or "system.integration_repository_cache" not in normalized
        ):
            continue
        calls.append({"tool": tool.name, "input": tool.input, "output": tool.output})
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
