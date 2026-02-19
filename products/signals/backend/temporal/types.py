from dataclasses import dataclass, field
from typing import Optional


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
class MatchedMetadata:
    """Metadata when a signal was matched to an existing report via a parent signal."""

    parent_signal_id: str
    match_query: str
    reason: str


@dataclass
class NoMatchMetadata:
    """Metadata when no existing signals matched and a new report was created."""

    reason: str
    rejected_signal_ids: list[str] = field(default_factory=list)


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
class SignalReportSummaryWorkflowInputs:
    """Inputs for the signal report summary workflow."""

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
    timestamp: str
    extra: dict = field(default_factory=dict)


def render_signal_to_text(
    signal: SignalData,
    index: Optional[int] = None,
) -> str:
    """Render a single signal to a text block for LLM consumption."""
    lines = [f"Signal {index}:" if index is not None else "Signal:"]
    lines.append(f"- Source: {signal.source_product} / {signal.source_type}")
    lines.append(f"- Weight: {signal.weight}")
    lines.append(f"- Timestamp: {signal.timestamp}")
    lines.append(f"- Description: {signal.content}")
    return "\n".join(lines)


def render_signals_to_text(signals: list[SignalData]) -> str:
    """Render a list of signals to text for LLM consumption."""
    blocks = []
    for i, signal in enumerate(signals):
        blocks.append(render_signal_to_text(signal, index=i + 1))
    return "\n\n".join(blocks)
