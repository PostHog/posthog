"""The active workflows that use an integration row. The integrations SDK loads this module."""

from products.integrations.backend.facade.contracts import IntegrationUsage
from products.workflows.backend.facade.api import get_active_workflows_using_integration

WORKFLOW_USAGE_TYPE = "workflow"


def integration_usages(team_id: int, integration_id: int) -> list[IntegrationUsage]:
    return [
        IntegrationUsage(type=WORKFLOW_USAGE_TYPE, id=flow.id, name=flow.name or flow.id)
        for flow in get_active_workflows_using_integration(team_id=team_id, integration_id=integration_id)
    ]
