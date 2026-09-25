"""Seeders for the Replay Vision MCP tool-use suite."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from posthog.models import Team
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

SCANNER_NAME = "Checkout friction"
FAILED_SESSION_ID = "0192f0e1-eval-4a5b-8c7d-checkoutfail01"


def seed_replay_vision_scanner(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """One paused monitor scanner with a transiently failed observation, and AI consent on."""
    team = Team.objects.select_related("organization").get(id=context.team_id)
    # The scanner, alert, backfill, and retry tools all refuse to run without AI consent.
    team.organization.is_ai_data_processing_approved = True
    team.organization.save(update_fields=["is_ai_data_processing_approved"])

    scanner = ReplayScanner.objects.create(
        team=team,
        name=SCANNER_NAME,
        scanner_type=ScannerType.MONITOR,
        scanner_config={"prompt": "Did the user struggle to complete checkout?"},
        model=ScannerModel.GEMINI_3_8_FLASH,
        # Paused so no scheduled sweep runs during the case.
        enabled=False,
    )
    observation = ReplayObservation.objects.create(
        team=team,
        scanner=scanner,
        session_id=FAILED_SESSION_ID,
        status=ObservationStatus.FAILED,
        error_reason="provider_transient:The model provider timed out.",
        triggered_by=ObservationTrigger.SCHEDULE,
        completed_at=timezone.now(),
    )
    return {"scanner_id": str(scanner.id), "failed_observation_id": str(observation.id)}


def seed_replay_vision_scanner_with_recordings(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """The same scanner plus recordings from the last week, so a backfill estimate finds sessions."""
    seed = seed_replay_vision_scanner(context)
    now = timezone.now()
    for day in range(1, 4):
        start = now - timedelta(days=day, hours=2)
        # Long and active enough to clear the video scanner's eligibility floor.
        produce_replay_summary(
            team_id=context.team_id,
            session_id=f"replay-vision-eval-backfill-{day}",
            distinct_id=f"replay-vision-eval-user-{day}",
            first_timestamp=start,
            last_timestamp=start + timedelta(minutes=5),
            active_milliseconds=120_000,
        )
    return seed
