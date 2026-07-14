"""Scorers for synthetic scout decision evals."""

from __future__ import annotations

import re
from typing import Any

from products.signals.eval.agentic.datasets import EvalCase, ScoutCase
from products.signals.eval.agentic.runners import ScoutDecisionOutput
from products.signals.eval.agentic.scorers_judge import ScoutDecisionQualityJudge
from products.signals.eval.agentic.scoring import DeterministicScorer, Score


def _normalize_term_text(text: str) -> str:
    """Fold formatting differences so '2,240'=='2240' and '3.6x'=='3.6×' match a required term."""
    return text.lower().replace(",", "").replace("×", "x")


# Structural prefix/decision words carry no topic signal, so they don't count as a scratchpad-key match.
_SCRATCHPAD_STOPWORDS = frozenset(
    {"dedupe", "report", "baseline", "improve", "remember", "close", "quiet", "skip", "only", "team"}
)


def _distinctive_tokens(key: str) -> set[str]:
    """Topic tokens (>=4 chars, non-structural) that identify what a scratchpad key is about."""
    return {t for t in re.split(r"[^a-z0-9]+", key.lower()) if len(t) >= 4 and t not in _SCRATCHPAD_STOPWORDS}


def _expectation(case: EvalCase):
    assert isinstance(case, ScoutCase)
    return case.expected


def _acceptable(expected: str | tuple[str | None, ...]) -> tuple[str | None, ...]:
    return (expected,) if isinstance(expected, str) else tuple(expected)


class ScoutDecisionScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("scout_decision_correct")

    def grade(self, case: EvalCase, output: ScoutDecisionOutput) -> list[Score]:
        exp = _expectation(case)
        ok = output.decision == exp.expected_decision
        return [Score.boolean(self.name, ok, reasoning=f"expected={exp.expected_decision} actual={output.decision}")]


class ScoutActionabilityScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("scout_actionability_correct")

    def grade(self, case: EvalCase, output: ScoutDecisionOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expected_actionability is None:
            return []
        acceptable = _acceptable(exp.expected_actionability)
        ok = output.actionability in acceptable
        return [Score.boolean(self.name, ok, reasoning=f"expected one of {acceptable} actual={output.actionability}")]


class ScoutPriorityScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("scout_priority_correct")

    def grade(self, case: EvalCase, output: ScoutDecisionOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expected_priority is None:
            return []
        acceptable = _acceptable(exp.expected_priority)
        ok = output.priority in acceptable
        return [Score.boolean(self.name, ok, reasoning=f"expected one of {acceptable} actual={output.priority}")]


class ScoutExistingReportScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("scout_existing_report_correct")

    def grade(self, case: EvalCase, output: ScoutDecisionOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expected_existing_report_id is None:
            return []
        ok = output.existing_report_id == exp.expected_existing_report_id
        return [
            Score.boolean(
                self.name,
                ok,
                reasoning=f"expected={exp.expected_existing_report_id} actual={output.existing_report_id}",
            )
        ]


class ScoutRepositoryScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("scout_repository_correct")

    def grade(self, case: EvalCase, output: ScoutDecisionOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.expected_repository is None:
            return []
        ok = output.repository == exp.expected_repository
        return [Score.boolean(self.name, ok, reasoning=f"expected={exp.expected_repository} actual={output.repository}")]


class ScoutEvidenceScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("scout_evidence_count")

    def grade(self, case: EvalCase, output: ScoutDecisionOutput) -> list[Score]:
        exp = _expectation(case)
        if exp.min_evidence_items <= 0:
            return []
        got = len([item for item in output.evidence if item.strip()])
        ok = got >= exp.min_evidence_items
        return [Score.boolean(self.name, ok, reasoning=f"expected>={exp.min_evidence_items} got={got}")]


class ScoutScratchpadScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("scout_scratchpad_keys")

    def grade(self, case: EvalCase, output: ScoutDecisionOutput) -> list[Score]:
        exp = _expectation(case)
        if not exp.required_scratchpad_keys:
            return []
        # The exact key string is an internal convention the model can't guess, so credit a topical
        # match: some emitted key must share a distinctive topic token with each expected key.
        emitted_tokens: set[str] = set()
        for key in output.scratchpad_keys:
            emitted_tokens |= {t for t in re.split(r"[^a-z0-9]+", key.lower()) if t}
        missing = [
            key
            for key in exp.required_scratchpad_keys
            if not (_distinctive_tokens(key) & emitted_tokens)
        ]
        return [Score.boolean(self.name, not missing, reasoning=f"missing_topic={missing}" if missing else "topic present")]


class ScoutSummaryTermsScorer(DeterministicScorer):
    def __init__(self) -> None:
        super().__init__("scout_summary_terms")

    def grade(self, case: EvalCase, output: ScoutDecisionOutput) -> list[Score]:
        exp = _expectation(case)
        checks: list[Score] = []
        blob = _normalize_term_text(output.summary)
        if exp.required_summary_terms:
            missing = [term for term in exp.required_summary_terms if _normalize_term_text(term) not in blob]
            checks.append(
                Score.boolean(
                    "scout_summary_required_terms",
                    not missing,
                    reasoning=f"missing={missing}" if missing else "all present",
                )
            )
        if exp.forbidden_summary_terms:
            present = [term for term in exp.forbidden_summary_terms if term.lower() in blob]
            checks.append(
                Score.boolean(
                    "scout_summary_forbidden_terms",
                    not present,
                    reasoning=f"present={present}" if present else "none present",
                )
            )
        return checks


def default_scout_scorers() -> tuple[Any, ...]:
    return (
        ScoutDecisionScorer(),
        ScoutActionabilityScorer(),
        ScoutPriorityScorer(),
        ScoutExistingReportScorer(),
        ScoutRepositoryScorer(),
        ScoutEvidenceScorer(),
        ScoutScratchpadScorer(),
        ScoutSummaryTermsScorer(),
        ScoutDecisionQualityJudge(),
    )
