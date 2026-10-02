from typing import Any, TypedDict

from django.db import transaction

from posthog.models.scoping.manager import resolve_effective_team_id

from products.tasks.backend.models import UserTasksConfig


class AgentPreferences(TypedDict):
    start_in_plan_mode: bool
    auto_publish_cloud_runs: bool


def _flag(value: Any) -> bool:
    return value if isinstance(value, bool) else False


def _with_defaults(stored: dict[str, Any] | None) -> AgentPreferences:
    stored = stored or {}
    return AgentPreferences(
        start_in_plan_mode=_flag(stored.get("start_in_plan_mode")),
        auto_publish_cloud_runs=_flag(stored.get("auto_publish_cloud_runs")),
    )


def get_user_agent_preferences(team_id: int, user_id: int) -> AgentPreferences:
    canonical_team_id = resolve_effective_team_id(team_id)
    stored = (
        UserTasksConfig.objects.for_team(canonical_team_id, canonical=True)
        .filter(user_id=user_id)
        .values_list("agent_preferences", flat=True)
        .first()
    )
    return _with_defaults(stored)


def update_user_agent_preferences(team_id: int, user_id: int, changes: dict[str, Any]) -> AgentPreferences:
    canonical_team_id = resolve_effective_team_id(team_id)
    configs = UserTasksConfig.objects.for_team(canonical_team_id, canonical=True)
    configs.get_or_create(team_id=canonical_team_id, user_id=user_id)
    with transaction.atomic():
        config = configs.select_for_update().get(user_id=user_id)
        preferences = _with_defaults({**(config.agent_preferences or {}), **changes})
        config.agent_preferences = dict(preferences)
        config.save(update_fields=["agent_preferences", "updated_at"])
    return preferences
