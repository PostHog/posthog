"""Temporal-free SDK for custom Signals agents.

The Temporal launchers (``arun_agent`` / ``run_agent`` for one-off runs,
``aschedule_agent`` / ``schedule_agent`` / ``unschedule_agent`` for recurring
schedules) live in ``products.signals.backend.temporal.custom_agent`` and depend
on this package; importing them from here would create a circular dependency.
The schedule argument type ``AgentScheduleSpec`` and the ``ScheduleAgentResult``
enum are Temporal-free, so they are re-exported here for convenience.
"""

from products.signals.backend.custom_agent.base import (
    NO_REPO,
    AIDataProcessingNotApprovedError,
    CustomAgentRepositorySelectionError,
    CustomAgentValidationError,
    CustomSignalAgent,
    MissingReportComponentError,
)
from products.signals.backend.custom_agent.schemas import (
    AgentScheduleSpec,
    CustomAgentAssignee,
    CustomAgentFinalReport,
    CustomAgentRunHandle,
    ScheduleAgentResult,
)

__all__ = [
    "NO_REPO",
    "AIDataProcessingNotApprovedError",
    "AgentScheduleSpec",
    "CustomAgentAssignee",
    "CustomAgentFinalReport",
    "CustomAgentRepositorySelectionError",
    "CustomAgentRunHandle",
    "CustomAgentValidationError",
    "CustomSignalAgent",
    "MissingReportComponentError",
    "ScheduleAgentResult",
]
