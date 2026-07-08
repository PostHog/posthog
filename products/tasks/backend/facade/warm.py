"""
Function facade for sandbox warming.

Callers decide when to warm and own their product-specific Task linkage, while
products/tasks owns quota checks, warm-pool capacity, Run creation, and workflow
dispatch. The boundary is function-shaped and returns DTOs, so callers do not
instantiate internal service classes or receive ORM models.
"""

from typing import Any
from uuid import UUID

from posthog.models.team import Team
from posthog.models.user import User

from products.tasks.backend.facade import contracts
from products.tasks.backend.logic.services.warm import SandboxWarmer, WarmResult
from products.tasks.backend.models import Task

__all__ = [
    "enforce_warm_quota",
    "warm_pool_at_capacity",
    "warm_task_run",
]


def _team_and_user(team_id: int, user_id: int) -> tuple[Team, User]:
    return Team.objects.get(pk=team_id), User.objects.get(pk=user_id)


def _warm_result_to_dto(result: WarmResult) -> contracts.WarmRunDTO:
    return contracts.WarmRunDTO(
        task_id=result.run.task_id,
        run_id=result.run.id,
        run_status=result.run.status,
        just_created=result.just_created,
    )


def enforce_warm_quota(origin_product: str, team_id: int, user_id: int) -> None:
    """Raise if the team may not warm a sandbox run for the origin product."""
    team, user = _team_and_user(team_id, user_id)
    SandboxWarmer.enforce_quota(origin_product, team, user)


def warm_pool_at_capacity(origin_product: str, team_id: int, user_id: int) -> bool:
    """Whether the user or organization already holds the max concurrent warm runs."""
    team, user = _team_and_user(team_id, user_id)
    return SandboxWarmer.at_capacity(origin_product, team, user)


def warm_task_run(
    task_id: str | UUID,
    team_id: int,
    user_id: int,
    *,
    mode: str = "interactive",
    extra_state: dict[str, Any] | None = None,
) -> contracts.WarmRunDTO:
    """Idempotently ensure a task has a warm run and return the run handle as a DTO."""
    task = Task.objects.select_related("team").get(id=task_id, team_id=team_id)
    user = User.objects.get(pk=user_id)
    return _warm_result_to_dto(SandboxWarmer(task, user=user).warm(mode=mode, extra_state=extra_state))
