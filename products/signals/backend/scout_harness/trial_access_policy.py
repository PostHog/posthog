from django.conf import settings


def local_scout_trial_team(team_id: int | None) -> bool:
    configured = settings.SCOUT_TRIALS_LOCAL_TEAM_ID
    if not settings.DEBUG or not configured:
        return False
    try:
        local_team_id = int(configured)
    except (TypeError, ValueError):
        return False
    return local_team_id > 0 and team_id == local_team_id


def scout_trial_team_allowed(team_id: int | None, *, production_team_id: int = 2) -> bool:
    if settings.DEBUG and settings.SCOUT_TRIALS_LOCAL_TEAM_ID:
        return local_scout_trial_team(team_id)
    return team_id == production_team_id
