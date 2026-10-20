from dataclasses import field
from typing import Any
from uuid import UUID

from asgiref.sync import sync_to_async

from posthog.dataclasses import frozen
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


@frozen
class StoredWorkflowForTest:
    """A workflow row as stored, for another product's test to check what it saved."""

    status: str
    origin_product: str | None
    actions: list[dict[str, Any]]
    trigger_masking: dict[str, Any] | None
    encrypted_inputs: dict[str, Any] | None = field(repr=False)


def stored_workflow_for_test(*, team_id: int, workflow_id: UUID) -> StoredWorkflowForTest:
    flow = HogFlow.objects.get(team_id=team_id, id=workflow_id)
    return StoredWorkflowForTest(
        status=flow.status,
        origin_product=flow.origin_product,
        actions=flow.actions,
        trigger_masking=flow.trigger_masking,
        encrypted_inputs=flow.encrypted_inputs,
    )


def count_workflows_for_test(*, team_id: int) -> int:
    return HogFlow.objects.filter(team_id=team_id).count()


def count_account_audience_for_test(*, team_id: int, filters: dict[str, Any]) -> int:
    return get_account_audience_count(Team.objects.get(pk=team_id), filters)


def list_account_audience_page_for_test(*, team_id: int, filters: dict[str, Any], cursor: str | None) -> list[str]:
    return get_account_audience_page(Team.objects.get(pk=team_id), filters, cursor)
