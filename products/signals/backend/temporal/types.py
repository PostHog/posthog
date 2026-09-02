import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional


def _parse_research_signal_buckets(raw: str) -> tuple[int, ...]:
    """Parse a comma-separated bucket list into a sorted, deduplicated, strictly positive tuple."""
    buckets = {int(part) for part in (item.strip() for item in raw.split(",")) if part}
    return tuple(sorted(b for b in buckets if b > 0))


# Cumulative assigned-signal counts at which a report researches, and by their number the most
# research passes any report gets. Between buckets, and past the last one, signals are still
# assigned and emitted but no research spawns. The defaults widen as they go because the
# signals-per-report distribution has a long tail: most reports never leave the first bucket, so
# most of the research this withholds would have re-read a report that barely moved. Empty disables
# research entirely, so keep at least one bucket.
RESEARCH_SIGNAL_BUCKETS = _parse_research_signal_buckets(os.getenv("SIGNAL_RESEARCH_SIGNAL_BUCKETS", "1,2,4,10"))


def next_research_bucket(signals_researched: int) -> Optional[int]:
    """The cumulative signal count at which a report's next research pass runs, or None for no pass.

    `signals_researched` is the count the report's last completed pass covered, so buckets it is
    already past are skipped instead of firing back to back — a report whose first pass ran at 5
    signals waits for 10, not for 2. Running out of buckets is also what caps the total: a report
    researched at the last bucket has no bucket above it, so it never researches again.

    Reading the completed count rather than a count of attempts is what keeps a run that pauses
    before researching — the quota gates in the summary workflow — from spending a pass, and what
    keeps a bucket crossing withheld by those gates claimable on the next signal.
    """
    return next((bucket for bucket in RESEARCH_SIGNAL_BUCKETS if bucket > signals_researched), None)


# How long a research run waits before starting, so signals arriving in a burst are researched
# together instead of once each. Signals cluster in time — a large share join a report within five
# minutes of the previous one — so a burst that straddles a bucket would otherwise research on the
# signal that crossed it and leave its siblings for the next bucket. The waiting workflow already
# owns the report's workflow ID, so signals landing during the wait collapse into it (see the
# WorkflowAlreadyStartedError handler in grouping) and the run then covers the whole burst. Applies
# to a report's first research too, so sibling signals join that run rather than spending the
# report's next bucket immediately after. 0 disables the wait.
RESEARCH_DEBOUNCE_SECONDS = int(os.getenv("SIGNAL_RESEARCH_DEBOUNCE_SECONDS", "0"))

# How long a report waits after research settles (READY, no pending signals) before its
# implementation task starts. A report re-promotes when a signal carries it to its next research
# bucket, so a signal landing just after research finishes would otherwise ship a PR for a summary
# that's about to be rewritten by the re-research. The wait lets that late signal fold into a
# re-research run instead. The waiting run still owns the report's workflow ID, so a signal arriving
# during the wait collapses into it (see the WorkflowAlreadyStartedError handler in grouping) and
# re-promotes the report to CANDIDATE; the run then loops to re-research rather than implement.
# 0 disables the wait.
IMPLEMENTATION_DEBOUNCE_SECONDS = int(os.getenv("SIGNAL_IMPLEMENTATION_DEBOUNCE_SECONDS", "900"))

# Orgs new to self-driving skip the implementation buffer: a team whose signals config was created
# within this window implements without the extra wait, so the product feels responsive while
# they're still evaluating it. Measured against SignalTeamConfig.created_at.
NEW_SELF_DRIVING_GRACE = timedelta(hours=24)


@dataclass
class EmitSignalInputs:
    team_id: int
    source_product: str
    source_type: str
    source_id: str
    description: str
    weight: float = 0.5
    extra: dict = field(default_factory=dict)
    # Optional fix guidance (separate from `extra`), shaped by the `SignalRemediation` schema and
    # validated against it at the emit boundary. Carried as a plain dict like `extra` so it survives
    # the Temporal/S3 JSON round-trip. Surfaced to the research agent as authoritative direction when
    # present; not required by any source.
    remediation: Optional[dict] = None


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
    # Seconds to wait before the first cycle, so a burst of signals is researched in one run rather
    # than one run each. Defaults to 0 so histories written before this field replay unchanged.
    debounce_seconds: int = 0


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
    """Normalized signal data used by report workflows.

    ClickHouse-backed instances include `inserted_at`; synthetic or adapted instances may omit it.
    """

    signal_id: str
    content: str
    source_product: str
    source_type: str
    source_id: str
    weight: float
    timestamp: datetime
    inserted_at: Optional[datetime] = None
    extra: dict = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Optional fix guidance (separate from `extra`); see EmitSignalInputs.remediation.
    remediation: Optional[dict] = None


def _render_extra_to_text(extra: dict) -> list[str]:
    """Render signal extra data to text lines for LLM consumption."""
    lines = []
    for key, value in extra.items():
        if key == "images":
            images = value or []
            rendered = ", ".join(f"[{img.get('author', 'unknown')}] {img['url']}" for img in images if img.get("url"))
            if rendered:
                lines.append(f"- images: {rendered}")
        else:
            lines.append(f"- {key}: {value}")
    return lines


def _render_remediation_to_text(remediation: dict) -> list[str]:
    """Render a remediation (SignalRemediation shape) to text lines for LLM consumption."""
    lines = ["- Remediation (authoritative guidance — follow it, then verify via the PostHog MCP):"]
    if agent := remediation.get("agent"):
        lines.append(f"  - Guidance: {agent}")
    if priority := remediation.get("priority"):
        lines.append(f"  - Suggested priority: {priority}")
    return lines


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
    if signal.remediation:
        lines.extend(_render_remediation_to_text(signal.remediation))
    if signal.extra:
        lines.extend(_render_extra_to_text(signal.extra))
    return "\n".join(lines)


def render_signals_to_text(signals: list[SignalData]) -> str:
    """Render a list of signals to text for LLM consumption."""
    blocks = []
    for i, signal in enumerate(signals):
        blocks.append(render_signal_to_text(signal, index=i + 1))
    return "\n\n".join(blocks)
