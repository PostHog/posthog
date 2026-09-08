"""Temporal registrations for Subscription-owned asynchronous work."""

from products.subscriptions.backend.temporal.artifacts import (
    ACTIVITIES as ARTIFACT_ACTIVITIES,
    WORKFLOWS as ARTIFACT_WORKFLOWS,
    PrepareProactiveArtifactWorkflow,
    prepare_proactive_artifact,
)
from products.subscriptions.backend.temporal.outcomes import (
    ACTIVITIES as OUTCOME_ACTIVITIES,
    WORKFLOWS as OUTCOME_WORKFLOWS,
    ProactiveOutcomeReadoutInput,
    ReadProactiveOutcomeWorkflow,
    read_proactive_outcome,
)

WORKFLOWS = [*ARTIFACT_WORKFLOWS, *OUTCOME_WORKFLOWS]
ACTIVITIES = [*ARTIFACT_ACTIVITIES, *OUTCOME_ACTIVITIES]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "PrepareProactiveArtifactWorkflow",
    "ProactiveOutcomeReadoutInput",
    "ReadProactiveOutcomeWorkflow",
    "prepare_proactive_artifact",
    "read_proactive_outcome",
]
