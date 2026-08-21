"""LLM-as-judge scorers for fuzzy quality dimensions.

These complement the deterministic scorers: deterministic checks assert the agent reached
the right *place* and *verdict*; judges assess the *quality* of the prose and reasoning that
a substring match can't capture. They run only when judging is enabled (``--judge`` / keys
present); otherwise the harness records them as skipped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from products.signals.eval.agentic.datasets import EvalCase, ImplementationCase, ResearchCase, ScoutCase
from products.signals.eval.agentic.scoring import JudgeScorer

if TYPE_CHECKING:
    from products.signals.backend.report_generation.research import ReportResearchOutput


class ResearchSummaryJudge(JudgeScorer):
    """Judges whether the report summary is specific, faithful, and grounded in the findings."""

    def __init__(self) -> None:
        super().__init__("summary_quality_judge")

    def build_judge_call(self, case: EvalCase, output: ReportResearchOutput) -> tuple[str, str, str | None]:
        assert isinstance(case, ResearchCase)
        findings = "\n".join(
            f"- signal {f.signal_id}: paths={f.relevant_code_paths}; data={f.data_queried[:200]}; verified={f.verified}"
            for f in output.effective_findings()
        )
        signals = "\n".join(f"- {s.content}" for s in case.signals)
        system = "You judge whether an engineering report summary faithfully reflects its research."
        prompt = (
            f"## Input signals\n{signals}\n\n"
            f"## Agent findings\n{findings}\n\n"
            f"## Report title\n{output.title}\n\n"
            f"## Report summary\n{output.summary}\n"
        )
        rubric = (
            "Score high only if the summary: (1) names the concrete culprit (specific component/API/query), "
            "(2) states impact grounded in the findings without inventing numbers, (3) is specific rather than "
            "generic, and (4) does not contradict the findings. Penalize vagueness and unsupported claims."
        )
        return system, prompt, rubric


class ImplementationFixJudge(JudgeScorer):
    """Judges whether the diff plausibly and correctly addresses the issue."""

    def __init__(self) -> None:
        super().__init__("fix_quality_judge")

    def build_judge_call(self, case: EvalCase, output: Any) -> tuple[str, str, str | None]:
        assert isinstance(case, ImplementationCase)
        system = "You judge whether a code diff correctly and minimally addresses a described issue."
        prompt = (
            f"## Issue\n{case.issue_prompt}\n\n"
            f"## Repository\n{case.repo}\n\n"
            f"## Proposed diff\n```diff\n{output.diff[:6000]}\n```\n"
        )
        rubric = (
            "Score high only if the diff plausibly fixes the described issue, edits the right code, and stays "
            "minimal and on-topic. Penalize changes that miss the root cause, are overly broad, or introduce "
            "obvious bugs."
        )
        return system, prompt, rubric


class ScoutDecisionQualityJudge(JudgeScorer):
    """Judges whether a scout decision is reasonable for the synthetic brief."""

    def __init__(self) -> None:
        super().__init__("scout_decision_quality_judge")

    def build_judge_call(self, case: EvalCase, output: Any) -> tuple[str, str, str | None]:
        assert isinstance(case, ScoutCase)
        expected = case.expected
        prompt = (
            f"## Scout\n{case.scout_name}\n\n"
            f"## Project profile\n{case.project_profile}\n\n"
            f"## Prior context\n{case.prior_context or 'No prior context.'}\n\n"
            f"## Current observations\n{case.observations}\n\n"
            f"## Candidate reports\n{case.candidate_reports or 'No matching reports found.'}\n\n"
            f"## Expected eval target\n"
            f"decision={expected.expected_decision}\n"
            f"actionability={expected.expected_actionability}\n"
            f"priority={expected.expected_priority}\n"
            f"existing_report_id={expected.expected_existing_report_id}\n"
            f"repository={expected.expected_repository}\n\n"
            f"## Model output\n"
            f"decision={output.decision}\n"
            f"summary={output.summary}\n"
            f"evidence={output.evidence}\n"
            f"actionability={output.actionability}\n"
            f"priority={output.priority}\n"
            f"existing_report_id={output.existing_report_id}\n"
            f"scratchpad_keys={output.scratchpad_keys}\n"
            f"repository={output.repository}\n"
        )
        rubric = (
            "Score high only if the scout decision is appropriate for the brief and expected target, avoids "
            "duplicate or noisy reports, uses the existing report when one clearly covers the same issue, and "
            "grounds its summary in concrete observations. Accept equivalent wording for priority/actionability "
            "when the underlying judgment is correct. Penalize hallucinated evidence, over-reporting, missing "
            "dedupe, or a decision that would create unnecessary user-facing noise."
        )
        return "You judge scout triage decisions for product-signal monitoring agents.", prompt, rubric
