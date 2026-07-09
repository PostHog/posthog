"""Eval cases: the inputs and ground truth for each agentic step.

A case is a single, self-contained eval unit: the inputs to feed the production step
function plus the ground truth to grade its output against. Cases are plain data
(frozen dataclasses) so a dataset is just a Python list that is trivial to read,
diff, and extend.

``SignalSpec`` is a thin, deterministic builder for the production ``SignalData``
dataclass (which carries a ``datetime`` and several required fields) so dataset
authors write only the fields that matter to the eval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from products.signals.eval.agentic.scoring import Scorer

if TYPE_CHECKING:
    from products.signals.backend.temporal.types import SignalData

# A fixed timestamp so rendered prompts (and their fingerprints) are reproducible.
_EVAL_EPOCH = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SignalSpec:
    """Deterministic builder for a production ``SignalData``.

    Only ``content`` is required; the rest default to a representative error-tracking
    signal so dataset rows stay terse.
    """

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
    """Base for all step cases. ``cassette`` names the recorded replay file (sans dir)."""

    case_id: str
    step: str
    scorers: tuple[Scorer, ...] = ()
    cassette: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class ResearchExpectation:
    """Ground truth for a research run.

    Substring matching keeps cases robust to incidental path/format variation while still
    asserting the agent reached the right code and reached the right verdict.

    ``expected_actionability`` / ``expected_priority`` accept either a single value or a tuple of
    acceptable values. Use a tuple for inherently-subjective judgments where more than one verdict
    is defensible (e.g. a vague signal that could be ``immediately_actionable`` or
    ``requires_human_input``) — this keeps live evals robust to LLM variance without lowering the
    bar on the deterministic dimensions (code paths, commits, summary).

    A ``None`` inside the ``expected_priority`` tuple accepts "no priority produced" — required
    whenever ``not_actionable`` is an acceptable verdict, since a not-actionable report carries no
    priority assessment.
    """

    expected_actionability: str | tuple[str, ...] | None = None  # ActionabilityChoice value(s)
    expected_priority: str | tuple[str | None, ...] | None = None  # Priority value(s), e.g. "P1" or ("P1", None)
    expected_already_addressed: bool | None = None
    expect_verified: bool | None = None
    # Per-signal: signal_id -> substrings at least one of which must appear in relevant_code_paths.
    expected_code_path_substrings: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Substrings that should appear (case-insensitive) somewhere in the title or summary.
    summary_must_mention: tuple[str, ...] = ()
    # Minimum number of commit hashes the agent should attribute across findings.
    min_commit_hashes: int = 0
    # Require a substantive `data_queried` (not "MCP unavailable") — only for signals the
    # project actually holds corroborating data for.
    expect_data_evidence: bool = False


@dataclass(frozen=True)
class ResearchCase(EvalCase):
    signals: tuple[SignalSpec, ...] = ()
    title: str | None = None
    summary: str | None = None
    expected: ResearchExpectation = field(default_factory=ResearchExpectation)
    # Repo this research is meant to run against (for live mode checkout / context only).
    repo: str | None = None


@dataclass(frozen=True)
class RepoSelectionExpectation:
    # Acceptable pick(s); a tuple when more than one candidate is defensible. None = no
    # expectation; use ``expect_null`` for "no plausible candidate".
    expected_repository: str | tuple[str, ...] | None = None
    # When True, any non-null pick is wrong (the case has no valid subject repo).
    expect_null: bool = False


@dataclass(frozen=True)
class RepoSelectionCase(EvalCase):
    signals: tuple[SignalSpec, ...] = ()
    # Pre-rendered context string. When empty, the harness renders ``signals`` to text.
    context: str | None = None
    candidate_repos: tuple[str, ...] = ()
    expected: RepoSelectionExpectation = field(default_factory=RepoSelectionExpectation)


@dataclass(frozen=True)
class ImplementationExpectation:
    # Substrings; at least one expected file path must contain one of these.
    expected_file_substrings: tuple[str, ...] = ()
    # File-path substrings that must NOT be touched (e.g. unrelated subsystems, lockfiles).
    forbidden_file_substrings: tuple[str, ...] = ()
    # Keywords the diff should contain (added/removed lines), case-insensitive.
    expected_diff_keywords: tuple[str, ...] = ()
    # Whether the patched repo is expected to still build / typecheck (live mode only).
    expect_builds: bool | None = None
    min_files_changed: int = 1
    max_files_changed: int | None = None


@dataclass(frozen=True)
class ImplementationCase(EvalCase):
    # Registry key of the OSS repo to operate on (see repos.py).
    repo: str = ""
    issue_prompt: str = ""
    expected: ImplementationExpectation = field(default_factory=ImplementationExpectation)
    # Path (relative to cassettes dir) of a recorded unified diff for replay scoring.
    patch: str | None = None


ScoutDecision = Literal["emit_report", "edit_report", "remember_only", "close_quiet", "skip"]


@dataclass(frozen=True)
class ScoutExpectation:
    expected_decision: ScoutDecision
    expected_actionability: str | tuple[str, ...] | None = None
    expected_priority: str | tuple[str | None, ...] | None = None
    expected_existing_report_id: str | None = None
    expected_repository: str | None = None
    min_evidence_items: int = 0
    required_summary_terms: tuple[str, ...] = ()
    forbidden_summary_terms: tuple[str, ...] = ()
    required_scratchpad_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoutCase(EvalCase):
    scout_name: str = "signals-scout-general"
    project_profile: str = ""
    prior_context: str = ""
    observations: str = ""
    candidate_reports: str = ""
    expected: ScoutExpectation = field(default_factory=lambda: ScoutExpectation(expected_decision="close_quiet"))
