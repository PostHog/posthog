from typing import Any

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.models import HogFlow

# Action configs are user-controlled JSON; cap traversal depth so a crafted deeply-nested
# config can't RecursionError the deletion guard (legitimate configs nest ~5 levels).
_MAX_CONFIG_DEPTH = 20

_TemplateCache = dict[str, HogFunctionTemplate | None]


def _node_references_integration(node: Any, integration_id: int, depth: int = 0) -> bool:
    if depth > _MAX_CONFIG_DEPTH:
        return False
    if isinstance(node, dict):
        value = node.get("integrationId")
        if value is not None and str(value) == str(integration_id):
            return True
        return any(_node_references_integration(child, integration_id, depth + 1) for child in node.values())
    if isinstance(node, list):
        return any(_node_references_integration(item, integration_id, depth + 1) for item in node)
    return False


def _function_action_references_integration(action: dict, integration_id: int, template_cache: _TemplateCache) -> bool:
    # Function actions store integration inputs as bare IDs; only the template's
    # inputs_schema knows which inputs are integration-typed.
    config = action.get("config") or {}
    template_id = config.get("template_id")
    if not template_id:
        return False
    if template_id not in template_cache:
        template_cache[template_id] = HogFunctionTemplate.get_template(template_id)
    template = template_cache[template_id]
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


def _action_references_integration(action: dict, integration_id: int, template_cache: _TemplateCache) -> bool:
    # Integrations are only consumed by function-style actions, via config.inputs — scanning
    # wider would let a planted integrationId in an unused field block deletion.
    if "function" not in (action.get("type") or ""):
        return False
    if _node_references_integration((action.get("config") or {}).get("inputs"), integration_id):
        return True
    return _function_action_references_integration(action, integration_id, template_cache)


def get_active_hog_flows_using_integration(team_id: int, integration_id: int) -> list[HogFlow]:
    """Active workflows whose live config references the given integration."""
    template_cache: _TemplateCache = {}
    return [
        flow
        for flow in HogFlow.objects.filter(team_id=team_id, status=HogFlow.State.ACTIVE)
        if any(
            _action_references_integration(action, integration_id, template_cache) for action in (flow.actions or [])
        )
    ]
