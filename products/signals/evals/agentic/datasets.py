from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from products.signals.backend.temporal.types import SignalData

_EVAL_EPOCH = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SignalSpec:
    content: str
    signal_id: str = "sig_eval_1"
    source_product: str = "error_tracking"
    source_type: str = "issue_created"
    source_id: str = "issue_eval_1"
    weight: float = 0.8
    extra: dict = field(default_factory=dict)
    remediation: dict | None = None

    def to_signal_data(self) -> SignalData:
        from products.signals.backend.temporal.types import (
            SignalData,  # noqa: PLC0415 — avoids temporal pkg import cycle
        )

        return SignalData(
            signal_id=self.signal_id,
            content=self.content,
            source_product=self.source_product,
            source_type=self.source_type,
            source_id=self.source_id,
            weight=self.weight,
            timestamp=_EVAL_EPOCH,
            extra=dict(self.extra),
            metadata={},
            remediation=self.remediation,
        )


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    step: str
    notes: str = ""


@dataclass(frozen=True)
class ResearchExpectation:
    expected_actionability: str | tuple[str, ...] | None = None
    expected_priority: str | tuple[str | None, ...] | None = None
    expected_already_addressed: bool | None = None
    expect_verified: bool | None = None
    expect_data_evidence: bool = False


@dataclass(frozen=True)
class ResearchCase(EvalCase):
    signals: tuple[SignalSpec, ...] = ()
    title: str | None = None
    summary: str | None = None
    expected: ResearchExpectation = field(default_factory=ResearchExpectation)
    repo: str | None = None


@dataclass(frozen=True)
class RepoSelectionExpectation:
    expected_repository: str | tuple[str, ...] | None = None
    expect_null: bool = False


@dataclass(frozen=True)
class RepoSelectionCase(EvalCase):
    signals: tuple[SignalSpec, ...] = ()
    context: str | None = None
    candidate_repos: tuple[str, ...] = ()
    judging_notes: str = ""
    expected: RepoSelectionExpectation = field(default_factory=RepoSelectionExpectation)


@dataclass(frozen=True)
class ImplementationCase(EvalCase):
    repo: str = ""
    issue_prompt: str = ""


ScoutOutcome = Literal["emit_report", "edit_report", "emit_signal", "remember", "no_output"]
ScoutSeed = Literal["error_burst", "error_low_volume", "funnel_regression", "funnel_denominator_drop"]


@dataclass(frozen=True)
class ScoutExpectation:
    expected_outcome: ScoutOutcome | tuple[ScoutOutcome, ...]


@dataclass(frozen=True)
class ScoutCase(EvalCase):
    skill_name: str = ""
    seed: ScoutSeed | None = None
    judging_notes: str = ""
    expected_query_tools: tuple[str, ...] = ()
    expected: ScoutExpectation = field(default_factory=lambda: ScoutExpectation(expected_outcome="no_output"))
