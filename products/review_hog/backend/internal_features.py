from django.conf import settings


def has_internal_features(team_id: int) -> bool:
    """Whether a project gets Flash and the automation settings: only the first configured ReviewHog team."""
    return bool(settings.REVIEWHOG_TEAM_IDS and team_id == settings.REVIEWHOG_TEAM_IDS[0])
