"""LLM-as-judge scorers for fuzzy quality dimensions.

These complement the deterministic scorers: deterministic checks assert the agent reached
the right *place* and *verdict*; judges assess the *quality* of the prose and reasoning that
a substring match can't capture. They run only when judging is enabled (``--judge`` / keys
present); otherwise the harness records them as skipped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from products.signals.eval.agentic.datasets import EvalCase, ImplementationCase, ResearchCase
from products.signals.eval.agentic.scoring import JudgeScorer

if TYPE_CHECKING:
    from products.signals.backend.report_generation.research import ReportResearchOutput


class ResearchSummaryJudge(JudgeScorer):
    """Judges whether the report summary is specific, faithful, and grounded in the findings."""

    pass_threshold = 0.6

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

    pass_threshold = 0.6

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
