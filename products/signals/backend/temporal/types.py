from dataclasses import dataclass, field


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
