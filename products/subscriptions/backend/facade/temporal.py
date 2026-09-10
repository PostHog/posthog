"""Workflow-safe contracts for Subscription-owned Temporal handoffs."""

from __future__ import annotations

from uuid import UUID

from posthog.dataclasses import frozen

PREPARE_PROACTIVE_ARTIFACT_WORKFLOW_NAME = "prepare-proactive-artifact"


@frozen
class ProactiveArtifactPreparationInput:
    team_id: int
    run_id: UUID
