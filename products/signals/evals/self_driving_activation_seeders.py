from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team

from products.posthog_ai.evals.error_tracking.seeders import seed_error_tracking_issues
from products.signals.backend.models import SignalTeamConfig
from products.tasks.backend.facade.agents import CustomPromptSandboxContext


def seed_errors_before_self_driving(context: CustomPromptSandboxContext) -> dict[str, Any]:
    seed = seed_error_tracking_issues(context)
    config = get_or_create_team_extension(Team.objects.get(id=context.team_id), SignalTeamConfig)
    onboarding = config.onboarding or {}
    return {**seed, "self_driving_completed_at": onboarding.get("completed_at"), "draft": onboarding.get("draft")}


def seed_errors_with_self_driving_active(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed the same issues on a team that finished Self-driving setup, so the activation rule stays silent."""
    seed = seed_error_tracking_issues(context)
    config = get_or_create_team_extension(Team.objects.get(id=context.team_id), SignalTeamConfig)
    completed_at = datetime.now(tz=UTC).isoformat()
    config.onboarding = {**(config.onboarding or {}), "completed_at": completed_at}
    config.save(update_fields=["onboarding"])
    return {**seed, "self_driving_completed_at": completed_at, "draft": config.onboarding.get("draft")}
