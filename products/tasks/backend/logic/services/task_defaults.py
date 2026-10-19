from typing import Any, TypedDict

from django.db import transaction

from posthog.models.scoping.manager import resolve_effective_team_id

from products.tasks.backend.models import UserTasksConfig


class TaskDefaults(TypedDict):
    # None means the person never set the value, so a client can apply its own default.
    start_in_plan_mode: bool | None
    auto_publish_cloud_runs: bool | None


def _flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _from_stored(stored: dict[str, Any] | None) -> TaskDefaults:
    stored = stored or {}
    return TaskDefaults(
        start_in_plan_mode=_flag(stored.get("start_in_plan_mode")),
        auto_publish_cloud_runs=_flag(stored.get("auto_publish_cloud_runs")),
    )


def get_user_task_defaults(team_id: int, user_id: int) -> TaskDefaults:
    canonical_team_id = resolve_effective_team_id(team_id)
    stored = (
        UserTasksConfig.objects.for_team(canonical_team_id, canonical=True)
        .filter(user_id=user_id)
        .values_list("task_defaults", flat=True)
        .first()
    )
    return _from_stored(stored)


def update_user_task_defaults(team_id: int, user_id: int, changes: dict[str, Any]) -> TaskDefaults:
    canonical_team_id = resolve_effective_team_id(team_id)
    configs = UserTasksConfig.objects.for_team(canonical_team_id, canonical=True)
    configs.get_or_create(team_id=canonical_team_id, user_id=user_id)
    with transaction.atomic():
        config = configs.select_for_update().get(user_id=user_id)
        defaults = _from_stored({**(config.task_defaults or {}), **changes})
        config.task_defaults = {key: value for key, value in defaults.items() if value is not None}
        config.save(update_fields=["task_defaults", "updated_at"])
    return defaults
