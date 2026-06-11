from typing import Any

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.models import HogFlow


def _node_references_integration(node: Any, integration_id: int) -> bool:
    if isinstance(node, dict):
        value = node.get("integrationId")
        if value is not None and str(value) == str(integration_id):
            return True
        return any(_node_references_integration(child, integration_id) for child in node.values())
    if isinstance(node, list):
        return any(_node_references_integration(item, integration_id) for item in node)
    return False


def _function_action_references_integration(action: dict, integration_id: int) -> bool:
    # Function actions store integration inputs as bare IDs; only the template's
    # inputs_schema knows which inputs are integration-typed.
    config = action.get("config") or {}
    template_id = config.get("template_id")
    if not template_id:
        return False
    template = HogFunctionTemplate.get_template(template_id)
    if not template:
        return False
    inputs = config.get("inputs") or {}
    for schema_item in template.inputs_schema or []:
        if schema_item.get("type") != "integration":
            continue
        value = (inputs.get(schema_item.get("key")) or {}).get("value")
        if isinstance(value, dict):
            value = value.get("integrationId")
        if value is not None and str(value) == str(integration_id):
            return True
    return False


def _action_references_integration(action: dict, integration_id: int) -> bool:
    if _node_references_integration(action.get("config"), integration_id):
        return True
    if "function" in (action.get("type") or ""):
        return _function_action_references_integration(action, integration_id)
    return False


def get_active_hog_flows_using_integration(team_id: int, integration_id: int) -> list[HogFlow]:
    """Active workflows whose live config references the given integration."""
    return [
        flow
        for flow in HogFlow.objects.filter(team_id=team_id, status=HogFlow.State.ACTIVE)
        if any(_action_references_integration(action, integration_id) for action in (flow.actions or []))
    ]
