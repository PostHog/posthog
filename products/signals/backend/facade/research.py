"""Report research output shapes, for agents in other products that produce output the signals pipeline consumes."""

from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    PriorityAssessment,
    ReportPresentationOutput,
    ReportResearchOutput,
    SignalFinding,
)

__all__ = [
    "ActionabilityAssessment",
    "ActionabilityChoice",
    "PriorityAssessment",
    "ReportPresentationOutput",
    "ReportResearchOutput",
    "SignalFinding",
]
