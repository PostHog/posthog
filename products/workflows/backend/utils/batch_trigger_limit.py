from django.conf import settings


def get_hogflow_batch_trigger_limit(team_id: int) -> int:
    if team_id in settings.HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS:
        return settings.HOGFLOW_BATCH_TRIGGER_LIMIT_ELEVATED
    return settings.HOGFLOW_BATCH_TRIGGER_LIMIT
