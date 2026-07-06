"""Scorers for the research step.

Graded against :class:`ResearchExpectation`. Substring matching on code paths and
summary keeps cases robust to incidental formatting while still asserting the agent
reached the right code and the right verdict. Each scorer covers one dimension so a
failure is legible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from products.signals.eval.agentic.datasets import EvalCase, ResearchCase
from products.signals.eval.agentic.scoring import DeterministicScorer, Score

if TYPE_CHECKING:
    from products.signals.backend.report_generation.research import ReportResearchOutput


def _expectation(case: EvalCase):
    assert isinstance(case, ResearchCase)
    return case.expected


def _acceptable(expected: str | tuple[str, ...]) -> tuple[str, ...]:
    """Normalize a single value or tuple of acceptable values to a tuple."""
    return (expected,) if isinstance(expected, str) else tuple(expected)


class ActionabilityScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("actionability_correct")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expected_actionability is None:
            return []
        try:
            actual = output.effective_actionability().actionability.value
        except ValueError:
            return [Score.boolean(self.name, False, reasoning="no actionability assessment produced")]
        acceptable = _acceptable(exp.expected_actionability)
        ok = actual in acceptable
        return [Score.boolean(self.name, ok, reasoning=f"expected one of {acceptable} actual={actual}")]


class PriorityScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("priority_correct")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expected_priority is None:
            return []
        prio = output.effective_priority()
        actual = prio.priority.value if prio else None
        acceptable = _acceptable(exp.expected_priority)
        ok = actual in acceptable
        return [Score.boolean(self.name, ok, reasoning=f"expected one of {acceptable} actual={actual}")]


class AlreadyAddressedScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("already_addressed_correct")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expected_already_addressed is None:
            return []
        try:
            actual = output.effective_actionability().already_addressed
        except ValueError:
            return [Score.boolean(self.name, False, reasoning="no actionability assessment produced")]
        ok = actual == exp.expected_already_addressed
        return [Score.boolean(self.name, ok, reasoning=f"expected={exp.expected_already_addressed} actual={actual}")]


class CodePathScorer(DeterministicScorer):
    """Fraction of expected signals whose finding cites a relevant code path."""

    def __init__(self) -> None:
        super().__init__("code_paths_found")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if not exp.expected_code_path_substrings:
            return []
        findings = {f.signal_id: f for f in output.effective_findings()}
        matched = 0
        details: list[str] = []
        for signal_id, substrings in exp.expected_code_path_substrings.items():
            finding = findings.get(signal_id)
            paths_blob = " ".join(finding.relevant_code_paths).lower() if finding else ""
            hit = any(sub.lower() in paths_blob for sub in substrings)
            matched += 1 if hit else 0
            details.append(f"{signal_id}:{'hit' if hit else 'miss'}")
        total = len(exp.expected_code_path_substrings)
        value = matched / total if total else 0.0
        return [Score.numeric(self.name, value, threshold=1.0, reasoning=", ".join(details))]


class FindingsVerifiedScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("findings_verified")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expect_verified is None:
            return []
        findings = output.effective_findings()
        if not findings:
            return [Score.boolean(self.name, False, reasoning="no findings produced")]
        all_match = all(f.verified == exp.expect_verified for f in findings)
        verified_count = sum(1 for f in findings if f.verified)
        return [
            Score.boolean(
                self.name,
                all_match,
                reasoning=f"expected verified={exp.expect_verified}; {verified_count}/{len(findings)} verified",
            )
        ]


class CommitAttributionScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("commit_attribution")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.min_commit_hashes <= 0:
            return []
        total = sum(len(f.relevant_commit_hashes) for f in output.effective_findings())
        return [
            Score.boolean(
                self.name,
                total >= exp.min_commit_hashes,
                reasoning=f"expected>={exp.min_commit_hashes} commit hashes, got {total}",
            )
        ]


_NO_DATA_MARKERS = (
    "no posthog mcp",
    "no mcp",
    "mcp tools were not",
    "not available",
    "unavailable",
    "could not be acted",
    "no relevant queries",
    "no queries were run",
    "were not available/surfaced",
)


class DataEvidenceScorer(DeterministicScorer):
    """Did the agent actually query/analyze the project's PostHog data?

    Proves the synthetic project's data can be picked up: at least one finding must carry a
    substantive `data_queried` that describes a real query and result — not a "MCP unavailable"
    or "no queries run" note. Only graded when the case expects data evidence (the project
    genuinely contains corroborating data for the signal).
    """

    def __init__(self) -> None:
        super().__init__("data_evidence_used")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if not exp.expect_data_evidence:
            return []
        findings = output.effective_findings()
        best = ""
        for f in findings:
            blob = (f.data_queried or "").strip()
            lowered = blob.lower()
            substantive = len(blob) >= 40 and not any(m in lowered for m in _NO_DATA_MARKERS)
            if substantive:
                return [Score.boolean(self.name, True, reasoning=f"queried data: {blob[:160]}")]
            if len(blob) > len(best):
                best = blob
        return [Score.boolean(self.name, False, reasoning=f"no substantive data query; best={best[:160]!r}")]


class SummaryMentionScorer(DeterministicScorer):
    """Fraction of required keywords present in the title+summary."""

    def __init__(self) -> None:
        super().__init__("summary_mentions")

    def grade(self, case: EvalCase, output: ReportResearchOutput) -> list[Score]:
        exp = _expectation(case)
        if not exp.summary_must_mention:
            return []
        blob = f"{output.title}\n{output.summary}".lower()
        hits = [kw for kw in exp.summary_must_mention if kw.lower() in blob]
        value = len(hits) / len(exp.summary_must_mention)
        missing = [kw for kw in exp.summary_must_mention if kw.lower() not in blob]
        return [
            Score.numeric(self.name, value, threshold=1.0, reasoning=f"missing={missing}" if missing else "all present")
        ]


def default_research_scorers() -> tuple[Any, ...]:
    """The full deterministic research scorer set; each no-ops when its expectation is unset."""
    return (
        ActionabilityScorer(),
        PriorityScorer(),
        AlreadyAddressedScorer(),
        CodePathScorer(),
        FindingsVerifiedScorer(),
        CommitAttributionScorer(),
        SummaryMentionScorer(),
        DataEvidenceScorer(),
    )
