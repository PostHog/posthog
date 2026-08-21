from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar

from products.posthog_ai.eval_harness.acp_log import parse_log
from products.posthog_ai.eval_harness.scorers import GRADED_ALIGNMENT_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import AsyncOnlyScorerMixin, Score, Scorer
from products.signals.backend.report_generation.research import ReportResearchOutput
from products.signals.evals.agentic.datasets import (
    EvalCase,
    ImplementationCase,
    RepoSelectionCase,
    ResearchCase,
    ScoutCase,
)
from products.signals.evals.agentic.runners import ImplementationOutput, RepoSelectionOutput, ScoutOutput
from products.signals.evals.agentic.scorers_repo_selection import repository_evidence_calls
from products.signals.evals.agentic.scoring import ScoringContext

OutputDecoder = Callable[[dict[str, Any]], Any]
CaseT = TypeVar("CaseT")


def _case_id(expected: dict[str, Any] | None) -> str | None:
    value = (expected or {}).get("case_id")
    return value if isinstance(value, str) else None


def _lookup_case(cases: Mapping[str, CaseT], expected: dict[str, Any] | None) -> CaseT | None:
    case_id = _case_id(expected)
    return cases.get(case_id) if case_id is not None else None


def decode_research(output: dict[str, Any]) -> ReportResearchOutput:
    return ReportResearchOutput.model_validate(output)


def decode_repo_selection(output: dict[str, Any]) -> RepoSelectionOutput:
    return RepoSelectionOutput.model_validate(output)


def decode_implementation(output: dict[str, Any]) -> ImplementationOutput:
    return ImplementationOutput.model_validate(output)


def decode_scout(output: dict[str, Any]) -> ScoutOutput:
    return ScoutOutput.model_validate(output)


def _tool_evidence(raw_log: str) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "input": tool.input,
            "output": (tool.output or "")[:2_000],
            "error": tool.is_error,
        }
        for tool in parse_log(raw_log).tools
    ]


class SignalsScorerAdapter(AsyncOnlyScorerMixin, Scorer):
    def __init__(
        self,
        scorer: Any,
        cases: Sequence[EvalCase],
        decoder: OutputDecoder,
        *,
        score_name: str | None = None,
    ) -> None:
        self._scorer = scorer
        self._cases = {case.case_id: case for case in cases}
        self._decoder = decoder
        self._score_name = score_name or scorer.name

    def _name(self) -> str:
        return self._score_name

    async def _run_eval_async(
        self,
        output: dict[str, Any] | None,
        expected: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Score:
        case_id = _case_id(expected)
        case = _lookup_case(self._cases, expected)
        if case is None:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"unknown case {case_id!r}"})
        if not output or output.get("timeout"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "workflow produced no output"})
        scores = await self._scorer.score(case, self._decoder(output), ScoringContext())
        selected = next((score for score in scores if score.name == self._name()), None)
        if selected is None:
            return Score(name=self._name(), score=None, metadata={"reason": "not applicable"})
        metadata = {
            key: value
            for key, value in {
                "passed": selected.passed,
                "reason": selected.reasoning,
                "status": selected.status,
                "error": selected.error,
            }.items()
            if value is not None
        }
        return Score(name=self._name(), score=selected.value, metadata=metadata)


def deterministic_scorers(
    domain_scorers: Sequence[Any], cases: Sequence[EvalCase], decoder: OutputDecoder
) -> list[Scorer]:
    scorers: list[Scorer] = []
    for scorer in domain_scorers:
        names = (
            ("scout_summary_required_terms", "scout_summary_forbidden_terms")
            if scorer.name == "scout_summary_terms"
            else (scorer.name,)
        )
        for name in names:
            scorers.append(SignalsScorerAdapter(scorer, cases, decoder, score_name=name))
    return scorers


_RESEARCH_JUDGE_PROMPT = """
You are grading an engineering research report produced from synthetic Signals inputs.

Inputs and rubric:
{{expected}}

Research output:
{{output}}

Choose exactly one grade:
- perfect: specific, faithful, grounded, and complete
- near_perfect: correct with only trivial omissions
- slightly_off: mostly correct with one meaningful weakness
- somewhat_misaligned: partially correct but important reasoning diverges
- strongly_misaligned: largely unsupported or contradictory
- useless: empty, incoherent, or unrelated
"""


class ResearchSummaryJudge(JudgedScorer):
    def __init__(self, cases: Sequence[ResearchCase], **kwargs: Any) -> None:
        self._cases = {case.case_id: case for case in cases}
        super().__init__(
            name="summary_quality_judge",
            prompt_template=_RESEARCH_JUDGE_PROMPT,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )

    def _prepare(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> dict[str, Any] | Score:
        case = _lookup_case(self._cases, expected)
        if case is None or not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "missing case or output"})
        # A timed-out case reaches the judge as `{"timeout": True, ...}`, which is truthy but has
        # no gradeable fields; score it 0.0 so the decoder never raises and drops the case from
        # the aggregate (see the JudgedScorer zero-score invariant).
        if output.get("timeout"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "workflow timed out"})
        research = decode_research(output)
        findings = [
            {
                "signal_id": finding.signal_id,
                "paths": finding.relevant_code_paths,
                "data": finding.data_queried,
                "verified": finding.verified,
            }
            for finding in research.effective_findings()
        ]
        return {
            "expected": json.dumps(
                {
                    "signals": [signal.content for signal in case.signals],
                    "expectation": str(case.expected),
                    "reference_facts": case.judging_notes,
                    "seeded_data": output.get("seed"),
                },
                indent=2,
            ),
            "output": json.dumps(
                {
                    "title": research.title,
                    "summary": research.summary,
                    "findings": findings,
                    "tool_calls": _tool_evidence(str(output.get("raw_log", ""))),
                },
                indent=2,
            ),
        }


_REPOSITORY_SELECTION_JUDGE_PROMPT = """
You are grading a repository selection from two plausible open-source candidates.

Request, candidates, and reference evidence:
{{expected}}

Selection:
{{output}}

Choose exactly one grade:
- perfect: selects the right owner and cites specific repository evidence
- near_perfect: correct with only a minor gap in the evidence
- slightly_off: correct repository but generic or partly mistaken reasoning
- somewhat_misaligned: defensible choice but misses stronger contrary evidence
- strongly_misaligned: wrong repository or unsupported reasoning
- useless: empty, incoherent, or unrelated
"""


class RepositorySelectionJudge(JudgedScorer):
    def __init__(self, cases: Sequence[RepoSelectionCase], **kwargs: Any) -> None:
        self._cases = {case.case_id: case for case in cases}
        super().__init__(
            name="repository_selection_quality_judge",
            prompt_template=_REPOSITORY_SELECTION_JUDGE_PROMPT,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )

    def _prepare(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> dict[str, Any] | Score:
        case = _lookup_case(self._cases, expected)
        if case is None or not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "missing case or output"})
        # A timed-out case reaches the judge as `{"timeout": True, ...}`, which is truthy but has
        # no gradeable fields; score it 0.0 so the decoder never raises and drops the case from
        # the aggregate (see the JudgedScorer zero-score invariant).
        if output.get("timeout"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "workflow timed out"})
        selection = decode_repo_selection(output)
        evidence_calls = repository_evidence_calls(selection.raw_log)
        return {
            "expected": json.dumps(
                {
                    "request": [signal.content for signal in case.signals],
                    "candidates": case.candidate_repos,
                    "expected_repository": case.expected.expected_repository,
                    "reference_evidence": case.judging_notes,
                },
                indent=2,
            ),
            "output": json.dumps(
                {
                    "repository": selection.repository,
                    "reason": selection.reason,
                    "repository_evidence_used": bool(evidence_calls),
                    "repository_evidence_calls": evidence_calls,
                },
                indent=2,
            ),
        }


_IMPLEMENTATION_JUDGE_PROMPT = """
You are grading whether a code diff correctly and minimally addresses an issue.

Issue and repository:
{{expected}}

Actual diff captured from the coding agent's tool log:
{{output}}

Choose exactly one grade:
- perfect: correct, focused, and complete
- near_perfect: correct with only trivial issues
- slightly_off: plausible with one meaningful weakness
- somewhat_misaligned: partially addresses the issue but has important gaps
- strongly_misaligned: mostly misses the issue or introduces obvious risk
- useless: empty or unrelated
"""


class ImplementationFixJudge(JudgedScorer):
    def __init__(self, cases: Sequence[ImplementationCase], **kwargs: Any) -> None:
        self._cases = {case.case_id: case for case in cases}
        super().__init__(
            name="fix_quality_judge",
            prompt_template=_IMPLEMENTATION_JUDGE_PROMPT,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )

    def _prepare(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> dict[str, Any] | Score:
        case = _lookup_case(self._cases, expected)
        if case is None or not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "missing case or output"})
        # A timed-out case reaches the judge as `{"timeout": True, ...}`, which is truthy but has
        # no gradeable fields; score it 0.0 so the decoder never raises and drops the case from
        # the aggregate (see the JudgedScorer zero-score invariant).
        if output.get("timeout"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "workflow timed out"})
        implementation = decode_implementation(output)
        if not implementation.diff:
            return Score(name=self._name(), score=0.0, metadata={"reason": "no actual diff captured"})
        return {
            "expected": json.dumps(
                {"repository": case.repo, "issue": case.issue_prompt, "reference_facts": case.judging_notes}, indent=2
            ),
            "output": json.dumps(
                {
                    "diff": implementation.diff[:12_000],
                    "tool_calls": _tool_evidence(implementation.raw_log),
                },
                indent=2,
            ),
        }


_SCOUT_JUDGE_PROMPT = """
You are grading a Signals scout run.

Canonical scout, seeded project facts, and expected persisted outcome:
{{expected}}

Production run summary and persisted side effects:
{{output}}

Choose exactly one grade:
- perfect: correct, conservative, grounded, and complete
- near_perfect: correct with only trivial omissions
- slightly_off: mostly correct with one meaningful weakness
- somewhat_misaligned: partially correct but important reasoning diverges
- strongly_misaligned: creates noise or invents evidence
- useless: empty, incoherent, or unrelated

A run that does not successfully query the seeded project data is useless, even if its final outcome happens to match.
"""


class ScoutDecisionQualityJudge(JudgedScorer):
    def __init__(self, cases: Sequence[ScoutCase], **kwargs: Any) -> None:
        self._cases = {case.case_id: case for case in cases}
        super().__init__(
            name="scout_decision_quality_judge",
            prompt_template=_SCOUT_JUDGE_PROMPT,
            choice_scores=GRADED_ALIGNMENT_CHOICE_SCORES,
            model=JUDGE_MODEL,
            max_completion_tokens=512,
            **kwargs,
        )

    def _prepare(self, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> dict[str, Any] | Score:
        case = _lookup_case(self._cases, expected)
        if case is None or not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "missing case or output"})
        # A timed-out case reaches the judge as `{"timeout": True, ...}`, which is truthy but has
        # no gradeable fields; score it 0.0 so the decoder never raises and drops the case from
        # the aggregate (see the JudgedScorer zero-score invariant).
        if output.get("timeout"):
            return Score(name=self._name(), score=0.0, metadata={"reason": "workflow timed out"})
        scout = decode_scout(output)
        return {
            "expected": json.dumps(
                {
                    "canonical_skill": case.skill_name,
                    "seeded_scenario": case.seed,
                    "reference_facts": case.judging_notes,
                    "expected_query_tools": case.expected_query_tools,
                    "outcome": case.expected.expected_outcome,
                },
                indent=2,
            ),
            "output": json.dumps(
                {
                    **scout.model_dump(mode="json", exclude={"raw_log"}),
                    "seed": output.get("seed"),
                    "tool_calls": _tool_evidence(scout.raw_log),
                },
                indent=2,
            ),
        }
