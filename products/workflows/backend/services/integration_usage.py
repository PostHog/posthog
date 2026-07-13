from typing import Any

from django.db.models import Count

from posthog.models.integration import Integration

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.models import HogFlow
from products.workflows.backend.models.hog_flow.hog_flow import HogFlowIntegration

# Action configs are user-controlled JSON; cap traversal depth so a crafted deeply-nested
# config can't RecursionError the deletion guard (legitimate configs nest ~5 levels).
_MAX_CONFIG_DEPTH = 20

_TemplateCache = dict[str, HogFunctionTemplate | None]


def _coerce_integration_id(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _collect_integration_ids(node: Any, ids: set[int], depth: int = 0) -> None:
    if depth > _MAX_CONFIG_DEPTH:
        return
    if isinstance(node, dict):
        integration_id = _coerce_integration_id(node.get("integrationId"))
        if integration_id is not None:
            ids.add(integration_id)
        for child in node.values():
            _collect_integration_ids(child, ids, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _collect_integration_ids(item, ids, depth + 1)


def _function_action_integration_ids(action: dict, template_cache: _TemplateCache) -> set[int]:
    # Function actions store integration inputs as bare IDs; only the template's
    # inputs_schema knows which inputs are integration-typed.
    config = action.get("config") or {}
    template_id = config.get("template_id")
    if not template_id:
        return set()
    if template_id not in template_cache:
        template_cache[template_id] = HogFunctionTemplate.get_template(template_id)
    template = template_cache[template_id]
    if not template:
        return set()
    ids: set[int] = set()
    inputs = config.get("inputs") or {}
    for schema_item in template.inputs_schema or []:
        if schema_item.get("type") != "integration":
            continue
        value = (inputs.get(schema_item.get("key")) or {}).get("value")
        if isinstance(value, dict):
            value = value.get("integrationId")
        integration_id = _coerce_integration_id(value)
        if integration_id is not None:
            ids.add(integration_id)
    return ids


def extract_integration_ids(actions: Any, template_cache: _TemplateCache | None = None) -> set[int]:
    """Integration IDs referenced by a hog flow's live action configs.

    Integrations are only consumed by function-style actions, via config.inputs — scanning
    wider would let a planted integrationId in an unused field count as a reference.
    """
    template_cache = template_cache if template_cache is not None else {}
    ids: set[int] = set()
    for action in actions or []:
        if not isinstance(action, dict) or "function" not in (action.get("type") or ""):
            continue
        _collect_integration_ids((action.get("config") or {}).get("inputs"), ids)
        ids |= _function_action_integration_ids(action, template_cache)
    return ids


def get_active_hog_flows_using_integration(team_id: int, integration_id: int) -> list[HogFlow]:
    """Active workflows whose live config references the given integration."""
    template_cache: _TemplateCache = {}
    return [
        flow
        for flow in HogFlow.objects.filter(team_id=team_id, status=HogFlow.State.ACTIVE)
        if integration_id in extract_integration_ids(flow.actions, template_cache)
    ]


def sync_hog_flow_integrations(flow: HogFlow) -> None:
    """Mirror the flow's JSON integration references into HogFlowIntegration rows.

    The JSON actions stay the runtime source of truth; the join rows exist for cheap reverse
    lookups (usage counts, deletion guards). Only integrations that exist in the flow's team
    are linked, so dangling or cross-team IDs in user-controlled JSON never create rows.
    Note: bulk_create/bulk_update writes bypass post_save and therefore this sync — rows
    catch up on the next regular save.
    """
    referenced_ids = extract_integration_ids(flow.actions)
    desired_ids: set[int] = set()
    if referenced_ids:
        desired_ids = set(
            Integration.objects.filter(team_id=flow.team_id, id__in=referenced_ids).values_list("id", flat=True)
        )
    existing_ids = set(HogFlowIntegration.objects.filter(hog_flow=flow).values_list("integration_id", flat=True))
    if removed_ids := existing_ids - desired_ids:
        HogFlowIntegration.objects.filter(hog_flow=flow, integration_id__in=removed_ids).delete()
    if added_ids := desired_ids - existing_ids:
        HogFlowIntegration.objects.bulk_create(
            [HogFlowIntegration(hog_flow=flow, integration_id=integration_id) for integration_id in added_ids],
            ignore_conflicts=True,
        )


def count_hog_flows_using_integrations(team_id: int, integration_ids: list[int]) -> dict[int, int]:
    """Number of non-archived hog flows referencing each integration, keyed by integration ID."""
    if not integration_ids:
        return {}
    rows = (
        HogFlowIntegration.objects.filter(
            integration_id__in=integration_ids,
            hog_flow__team_id=team_id,
        )
        .exclude(hog_flow__status=HogFlow.State.ARCHIVED)
        .values("integration_id")
        .annotate(count=Count("id"))
    )
    return {row["integration_id"]: row["count"] for row in rows}
