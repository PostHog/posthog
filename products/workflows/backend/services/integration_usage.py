from typing import Any
from uuid import UUID

from posthog.models.integration import Integration

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
        values = node.get("integrationIds")
        if isinstance(values, list) and any(str(value) == str(integration_id) for value in values):
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


def enabled_flows_using(*, team_id: int, integration_id: int) -> list[HogFlow]:
    """Active and waiting workflows whose live config references the given integration."""
    template_cache: _TemplateCache = {}
    return [
        flow
        for flow in HogFlow.objects.filter(
            team_id=team_id, status__in=[HogFlow.State.ACTIVE, HogFlow.State.WAITING_FOR_DOMAIN]
        )
        if any(
            _action_references_integration(action, integration_id, template_cache) for action in (flow.actions or [])
        )
    ]


def _email_sender_id(action: dict) -> int | None:
    sender = ((((action.get("config") or {}).get("inputs") or {}).get("email") or {}).get("value") or {}).get("from")
    sender_id = sender.get("integrationId") if isinstance(sender, dict) else None
    try:
        return int(sender_id) if sender_id is not None else None
    except (TypeError, ValueError):
        return None


def email_senders_of(flow: HogFlow) -> frozenset[int]:
    """The email integrations the workflow's live email steps send from."""
    return frozenset(
        sender_id
        for action in flow.actions or []
        if isinstance(action, dict)
        and action.get("type") == "function_email"
        and (sender_id := _email_sender_id(action)) is not None
    )


def unverified_senders(*, team_id: int, sender_ids: frozenset[int]) -> frozenset[int]:
    """The senders among ``sender_ids`` that exist and are not verified yet. A sender that no longer exists
    can never verify, so it does not hold a workflow back."""
    if not sender_ids:
        return frozenset()
    senders = Integration.objects.filter(team_id=team_id, kind="email", id__in=sender_ids).only("id", "config")
    return frozenset(sender.id for sender in senders if not (sender.config or {}).get("verified"))


def waiting_flows_using(*, team_id: int, sender_ids: frozenset[int]) -> list[UUID]:
    """The waiting workflows of the team that send email from any of ``sender_ids``."""
    if not sender_ids:
        return []
    waiting = HogFlow.objects.filter(team_id=team_id, status=HogFlow.State.WAITING_FOR_DOMAIN).only("id", "actions")
    return [flow.id for flow in waiting if email_senders_of(flow) & sender_ids]
