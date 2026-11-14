import json

from django.core.cache import cache

import structlog
import posthoganalytics

from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

RUN_PER_WAKE_FLAG = "tasks-run-per-wake"
RUN_PER_WAKE_CACHE_SECONDS = 60
_ON = "on"
_OFF = "off"


def starts_new_run_per_wake(profile_key: str | None, team_id: int) -> bool:
    if not profile_key:
        return False
    key = f"tasks:run_per_wake:{team_id}:{profile_key}"
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return cached == _ON
    enabled = _resolve(profile_key, team_id)
    try:
        cache.set(key, _ON if enabled else _OFF, RUN_PER_WAKE_CACHE_SECONDS)
    except Exception:
        logger.warning("task_run_per_wake_cache_failed", profile=profile_key, team_id=team_id, exc_info=True)
    return enabled


def _resolve(profile_key: str, team_id: int) -> bool:
    try:
        team = Team.objects.only("uuid", "organization_id").get(pk=team_id)
        organization_id = str(team.organization_id)
        payload = posthoganalytics.get_feature_flag_payload(
            RUN_PER_WAKE_FLAG,
            distinct_id=str(team.uuid),
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
    except Exception:
        logger.warning("task_run_per_wake_unresolved", profile=profile_key, team_id=team_id, exc_info=True)
        return False
    return isinstance(payload, dict) and payload.get(profile_key) == _ON
