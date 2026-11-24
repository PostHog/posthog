from typing import Any

from posthog.models import Team

from products.error_tracking.backend.logic.issue_summary_config import ISSUE_SUMMARY_FLAG
from products.error_tracking.backend.logic.team_flags import local_flag_definitions_loaded, team_flag_enabled
from products.error_tracking.backend.models import ErrorTrackingSettings

from .base import Recommendation


class IssueSummariesRecommendation(Recommendation):
    type = "issue_summaries"
    refresh_interval = None

    def available_team_ids(self, team_ids: list[int]) -> list[int]:
        # Check once for the whole batch. Otherwise each team makes its own blocking definitions call, and a sweep batch
        # can run past its heartbeat timeout, which also stops the other recommendation types from refreshing.
        if not local_flag_definitions_loaded():
            return []
        # This is the same local-only flag check as available_ai_features, which decides if the settings page shows the
        # AI features section. Thus this recommendation never points to a section that the project does not show. Also,
        # an issue list load never waits on a remote flag call.
        flagged = [
            team_id
            for team_id in team_ids
            if team_flag_enabled(ISSUE_SUMMARY_FLAG, team_id, only_evaluate_locally=True)
        ]
        if not flagged:
            return []
        # The settings serializer refuses to enable summaries until the organization approves AI data processing. Without
        # this filter, the banner sends an unapproved organization to a switch that fails on save.
        approved = set(
            Team.objects.filter(id__in=flagged, organization__is_ai_data_processing_approved=True).values_list(
                "id", flat=True
            )
        )
        return [team_id for team_id in flagged if team_id in approved]

    def is_completed(self, meta: dict[str, Any]) -> bool:
        return meta.get("enabled") is True

    def compute_batch(self, team_ids: list[int]) -> dict[int, dict[str, Any]]:
        enabled_team_ids = set(
            ErrorTrackingSettings.objects.filter(team_id__in=team_ids, ai_issue_summaries_enabled=True).values_list(
                "team_id", flat=True
            )
        )
        return {team_id: {"enabled": team_id in enabled_team_ids} for team_id in team_ids}
