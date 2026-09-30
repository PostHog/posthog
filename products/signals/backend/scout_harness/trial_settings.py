from django.conf import settings


def local_trial_project_ids() -> set[int]:
    if not settings.DEBUG:
        return set()
    return set(settings.SCOUT_LIVE_TRIALS_LOCAL_PROJECT_IDS)


def is_trial_project_allowed(project_id: int) -> bool:
    return project_id == 2 or project_id in local_trial_project_ids()
