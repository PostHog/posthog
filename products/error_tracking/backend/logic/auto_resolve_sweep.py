from django.db.models import Exists, OuterRef

from posthog.dataclasses import frozen

from products.error_tracking.backend.logic.auto_resolve import find_auto_resolve_candidates
from products.error_tracking.backend.logic.issue_mutations import auto_resolve_issues
from products.error_tracking.backend.logic.team_flags import team_flag_enabled
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSettings

AUTO_RESOLVE_FLAG = "error-tracking-auto-resolve"

# Issues resolved in one transaction, so row locks stay short.
_RESOLVE_CHUNK_SIZE = 500


@frozen
class AutoResolveRun:
    after_days: int
    resolved_count: int


def auto_resolve_team_ids() -> list[int]:
    """Teams the daily run visits: the setting is on, the rollout flag is on, and at least one issue is active.

    Teams with no recent exceptions are exactly the ones whose issues went quiet, so the selection never
    looks at exception volume.
    """
    team_ids = (
        ErrorTrackingSettings.objects.filter(auto_resolve_after_days__isnull=False)
        .filter(
            Exists(
                ErrorTrackingIssue.objects.filter(team_id=OuterRef("team_id"), status=ErrorTrackingIssue.Status.ACTIVE)
            )
        )
        .order_by("team_id")
        .values_list("team_id", flat=True)
    )
    return [team_id for team_id in team_ids if team_flag_enabled(AUTO_RESOLVE_FLAG, team_id)]


def auto_resolve_team(team_id: int) -> AutoResolveRun | None:
    """Resolve the team's quiet active issues. Return None when the team has auto-resolve off."""
    settings = ErrorTrackingSettings.objects.select_related("team").filter(team_id=team_id).first()
    if settings is None or settings.auto_resolve_after_days is None:
        return None
    after_days = settings.auto_resolve_after_days
    candidate_ids = find_auto_resolve_candidates(settings.team, after_days)
    resolved_count = 0
    for start in range(0, len(candidate_ids), _RESOLVE_CHUNK_SIZE):
        chunk = candidate_ids[start : start + _RESOLVE_CHUNK_SIZE]
        resolved_count += len(auto_resolve_issues(team_id, chunk, after_days=after_days))
    return AutoResolveRun(after_days=after_days, resolved_count=resolved_count)
