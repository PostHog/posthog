from typing import Literal

from products.workflows.backend.models import HogFlow


async def create_workflow_for_test(
    *,
    team_id: int,
    created_by_id: int,
    name: str,
    status: Literal["active", "archived", "draft"],
) -> None:
    await HogFlow.objects.acreate(team_id=team_id, created_by_id=created_by_id, name=name, status=status)
