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
class ExistingReportMatch:
    report_id: str


@dataclass
class NewReportMatch:
    title: str
    summary: str


MatchResult = ExistingReportMatch | NewReportMatch


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
    header = f"Signal {index}:" if index is not None else "Signal:"
    lines = [header]
    lines.append(f"- Source: {signal.source_product} / {signal.source_type}")
    lines.append(f"- Weight: {signal.weight}")
    lines.append(f"- Timestamp: {signal.timestamp}")
    lines.append(f"- Description: {signal.content}")
    if signal.extra:
        lines.append(f"- Extra metadata: {signal.extra}")
    return "\n".join(lines)


def render_signals_to_text(signals: list[SignalData]) -> str:
    """Render a list of signals to text for LLM consumption."""
    blocks = []
    for i, signal in enumerate(signals):
        blocks.append(render_signal_to_text(signal, index=i + 1))
    return "\n\n".join(blocks)
