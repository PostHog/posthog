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

    # Source-specific impact lines from extra
    extra = signal.extra
    match signal.source_product:
        case "session_replay":
            metrics = extra.get("metrics", {})
            user_count = metrics.get("relevant_user_count")
            active_users = metrics.get("active_users_in_period")
            occurrence_count = metrics.get("occurrence_count")
            parts = []
            if user_count is not None and active_users:
                parts.append(f"{user_count} users affected (of {active_users:,} active)")
            elif user_count is not None:
                parts.append(f"{user_count} users affected")
            if occurrence_count is not None:
                parts.append(f"{occurrence_count} occurrences")
            if parts:
                lines.append(f"- Impact: {', '.join(parts)}")
        case "zendesk":
            prio = extra.get("priority")
            ticket_type = extra.get("type")
            parts = []
            if prio:
                parts.append(f"Zendesk priority: {prio}")
            if ticket_type:
                parts.append(f"type: {ticket_type}")
            if parts:
                lines.append(f"- Severity: {', '.join(parts)}")
        case "linear":
            priority_label = extra.get("priority_label")
            identifier = extra.get("identifier")
            parts = []
            if identifier:
                parts.append(identifier)
            if priority_label:
                parts.append(f"priority: {priority_label}")
            if parts:
                lines.append(f"- Severity: {', '.join(parts)}")
        case "github":
            labels = extra.get("labels", [])
            if labels:
                lines.append(f"- Labels: {', '.join(str(item) for item in labels)}")

    return "\n".join(lines)


def render_signals_to_text(signals: list[SignalData]) -> str:
    """Render a list of signals to text for LLM consumption."""
    blocks = []
    for i, signal in enumerate(signals):
        blocks.append(render_signal_to_text(signal, index=i + 1))
    return "\n\n".join(blocks)
