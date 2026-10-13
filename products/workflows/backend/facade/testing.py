from typing import Any

from asgiref.sync import sync_to_async

from posthog.models.team import Team

from products.workflows.backend.facade.contracts import WorkflowSummary
from products.workflows.backend.models import HogFlow
from products.workflows.backend.services.account_audience import get_account_audience_count, get_account_audience_page


def create_workflow_for_test(
    *,
    team_id: int,
    name: str | None = None,
    status: str = "draft",
    created_by_id: int | None = None,
    trigger: dict[str, Any] | None = None,
    actions: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
) -> WorkflowSummary:
    """Seed a workflow row. Fields left as None take the model defaults."""
    optional = {"name": name, "trigger": trigger, "actions": actions, "edges": edges}
    flow = HogFlow.objects.create(
        team_id=team_id,
        status=status,
        created_by_id=created_by_id,
        **{field: value for field, value in optional.items() if value is not None},
    )
    return WorkflowSummary(id=str(flow.id), name=flow.name or "", status=flow.status)


acreate_workflow_for_test = sync_to_async(create_workflow_for_test)


def count_account_audience_for_test(*, team_id: int, filters: dict[str, Any]) -> int:
    return get_account_audience_count(Team.objects.get(pk=team_id), filters)


def list_account_audience_page_for_test(*, team_id: int, filters: dict[str, Any], cursor: str | None) -> list[str]:
    return get_account_audience_page(Team.objects.get(pk=team_id), filters, cursor)
