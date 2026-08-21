from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar

from products.posthog_ai.eval_harness.scorers import GRADED_ALIGNMENT_CHOICE_SCORES, JUDGE_MODEL, JudgedScorer
from products.posthog_ai.eval_harness.scorers.contract import AsyncOnlyScorerMixin, Score, Scorer
from products.signals.backend.report_generation.research import ReportResearchOutput
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.eval.agentic.datasets import EvalCase, ImplementationCase, ResearchCase, ScoutCase
from products.signals.eval.agentic.runners import ImplementationOutput, ScoutDecisionOutput
from products.signals.eval.agentic.scoring import ScoringContext

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


def decode_repo_selection(output: dict[str, Any]) -> RepoSelectionResult:
    return RepoSelectionResult.model_validate(output)


def decode_implementation(output: dict[str, Any]) -> ImplementationOutput:
    return ImplementationOutput.model_validate(output)


def decode_scout(output: dict[str, Any]) -> ScoutDecisionOutput:
    return ScoutDecisionOutput.model_validate(output)


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
                },
                indent=2,
            ),
            "output": json.dumps(
                {"title": research.title, "summary": research.summary, "findings": findings},
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
        implementation = decode_implementation(output)
        if not implementation.diff:
            return Score(name=self._name(), score=0.0, metadata={"reason": "no actual diff captured"})
        return {
            "expected": json.dumps({"repository": case.repo, "issue": case.issue_prompt}, indent=2),
            "output": implementation.diff[:12_000],
        }


_SCOUT_JUDGE_PROMPT = """
You are grading a conservative Signals scout triage decision.

Synthetic brief and expected target:
{{expected}}

Model decision:
{{output}}

Choose exactly one grade:
- perfect: correct, conservative, grounded, and complete
- near_perfect: correct with only trivial omissions
- slightly_off: mostly correct with one meaningful weakness
- somewhat_misaligned: partially correct but important reasoning diverges
- strongly_misaligned: creates noise, misses dedupe, or invents evidence
- useless: empty, incoherent, or unrelated
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
        scout = decode_scout(output)
        return {
            "expected": json.dumps(
                {
                    "profile": case.project_profile,
                    "prior": case.prior_context,
                    "observations": case.observations,
                    "candidate_reports": case.candidate_reports,
                    "target": str(case.expected),
                },
                indent=2,
            ),
            "output": scout.model_dump_json(indent=2, exclude={"raw_log"}),
        }
