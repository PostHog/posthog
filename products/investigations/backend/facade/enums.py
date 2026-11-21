from posthog.enums import LabeledStrEnum


class InvestigationStage(LabeledStrEnum):
    INVESTIGATING = "investigating"
    REVIEW = "review"
    MONITORING = "monitoring"
    CLOSED = "closed"


class InvestigationHypothesisStatus(LabeledStrEnum):
    OPEN = "open"
    SUPPORTED = "supported"
    RULED_OUT = "ruled_out"
