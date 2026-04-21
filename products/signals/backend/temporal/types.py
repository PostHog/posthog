from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class EmitSignalInputs:
    team_id: int
    source_product: str
    source_type: str
    source_id: str
    description: str
    weight: float = 0.5
    extra: dict = field(default_factory=dict)


@dataclass
class SignalCandidate:
    signal_id: str
    report_id: str
    content: str
    source_product: str
    source_type: str
    distance: float


@dataclass
class ReportContext:
    """Lightweight context about a report for group-aware matching."""

    report_id: str
    title: str
    signal_count: int


@dataclass
class SpecificityMetadata:
    """Result of the PR-specificity verification gate."""

    pr_title: str
    specific_enough: bool
    reason: str


@dataclass
class MatchedMetadata:
    """Metadata when a signal was matched to an existing report via a parent signal."""

    parent_signal_id: str
    match_query: str
    reason: str
    specificity: Optional[SpecificityMetadata] = None


@dataclass
class NoMatchMetadata:
    """Metadata when no existing signals matched and a new report was created."""

    reason: str
    rejected_signal_ids: list[str] = field(default_factory=list)
    specificity_rejection: Optional[SpecificityMetadata] = None


MatchMetadata = MatchedMetadata | NoMatchMetadata


@dataclass
class ExistingReportMatch:
    report_id: str
    match_metadata: MatchedMetadata


@dataclass
class NewReportMatch:
    title: str
    summary: str
    match_metadata: NoMatchMetadata


MatchResult = ExistingReportMatch | NewReportMatch


@dataclass
class TeamSignalGroupingInput:
    """Inputs for the team signal grouping entity workflow."""

    team_id: int
    pending_signals: list["EmitSignalInputs"] = field(default_factory=list)


@dataclass
class BufferSignalsInput:
    """Inputs for the buffer signals workflow."""

    team_id: int
    # Signals that arrived between the last drain and continue_as_new.
    # Small in practice (only a few signals can sneak in during two activity calls),
    # but must be carried over to avoid dropping them.
    pending_signals: list["EmitSignalInputs"] = field(default_factory=list)


@dataclass
class TeamSignalGroupingV2Input:
    """Inputs for the v2 grouping workflow."""

    team_id: int
    pending_batch_keys: list[str] = field(default_factory=list)
    paused_until: Optional[datetime] = None


@dataclass
class ReadSignalsFromS3Input:
    """Activity input for reading a signal batch."""

    object_key: str


@dataclass
class ReadSignalsFromS3Output:
    """Activity output: the deserialized signals."""

    signals: list["EmitSignalInputs"]


@dataclass
class SignalReportSummaryWorkflowInputs:
    """Inputs for the signal report summary workflow."""

    team_id: int
    report_id: str


@dataclass
class SignalReportReingestionWorkflowInputs:
    """Inputs for the signal report reingestion workflow."""

    team_id: int
    report_id: str


@dataclass
class TeamSignalReingestionWorkflowInputs:
    """Inputs for the team-wide signal reingestion workflow."""

    team_id: int
    delete_only: bool = False


@dataclass
class SignalReportDeletionWorkflowInputs:
    """Inputs for the signal report deletion workflow."""

    team_id: int
    report_id: str


@dataclass
class SignalTypeExample:
    """One example signal per unique (source_product, source_type) pair, used to give the LLM context."""

    source_product: str
    source_type: str
    content: str
    timestamp: str
    extra: dict = field(default_factory=dict)


@dataclass
class SignalData:
    """Data about a signal fetched from ClickHouse."""

    signal_id: str
    content: str
    source_product: str
    source_type: str
    source_id: str
    weight: float
    timestamp: datetime
    extra: dict = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def _render_extra_to_text(extra: dict) -> list[str]:
    """Render signal extra data to text lines for LLM consumption."""
    return [f"- {key}: {value}" for key, value in extra.items()]


def render_signal_to_text(
    signal: SignalData,
    index: Optional[int] = None,
) -> str:
    """Render a single signal to a text block for LLM consumption."""
    lines = [f"Signal {index}:" if index is not None else "Signal:"]
    lines.append(f"- Source: {signal.source_product} / {signal.source_type}")
    lines.append(f"- Weight: {signal.weight}")
    lines.append(f"- Timestamp: {signal.timestamp.isoformat()}")
    lines.append(f"- Description: {signal.content}")
    if signal.extra:
        lines.extend(_render_extra_to_text(signal.extra))
    return "\n".join(lines)


def render_signals_to_text(signals: list[SignalData]) -> str:
    """Render a list of signals to text for LLM consumption."""
    blocks = []
    for i, signal in enumerate(signals):
        blocks.append(render_signal_to_text(signal, index=i + 1))
    return "\n\n".join(blocks)
