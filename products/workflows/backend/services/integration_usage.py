from typing import Any
from uuid import UUID

from django.db.models import QuerySet

from posthog.models.integration import Integration

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.facade.enums import ENABLED_HOG_FLOW_STATES
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
        for flow in HogFlow.objects.filter(team_id=team_id, status__in=ENABLED_HOG_FLOW_STATES)
        if any(
            _action_references_integration(action, integration_id, template_cache) for action in (flow.actions or [])
        )
    ]


def _as_sender_id(value: object) -> int | None:
    try:
        return int(value) if isinstance(value, int | str) else None
    except ValueError:
        return None


def _dict_at(node: object, *keys: str) -> dict:
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _email_sender_ids(action: dict) -> frozenset[int]:
    # Same rule as the sender selection in Node: a non-empty rotation replaces the single sender.
    sender = _dict_at(action, "config", "inputs", "email", "value", "from")
    rotation = sender.get("integrationIds")
    configured = rotation if isinstance(rotation, list) and rotation else [sender.get("integrationId")]
    return frozenset(sender_id for value in configured if (sender_id := _as_sender_id(value)) is not None)


def email_senders_of(flow: HogFlow) -> frozenset[int]:
    """The email integrations the workflow's live email steps send from."""
    return frozenset().union(
        *(
            _email_sender_ids(action)
            for action in flow.actions or []
            if isinstance(action, dict) and action.get("type") == "function_email"
        )
    )


def _email_integrations(team_id: int, sender_ids: frozenset[int]) -> "QuerySet[Integration]":
    return Integration.objects.filter(team_id=team_id, kind="email", id__in=sender_ids).only("id", "config")


def _is_unverified(sender: Integration) -> bool:
    return not (sender.config or {}).get("verified")


def lock_unverified_senders(*, team_id: int, sender_ids: frozenset[int]) -> frozenset[int]:
    """The senders among ``sender_ids`` that exist and are not verified yet. A sender that no longer exists
    can never verify, so it does not hold a workflow back. Locks the senders until the caller's transaction
    ends, so a verification of them waits for the caller's status write and then finds it."""
    if not sender_ids:
        return frozenset()
    return frozenset(
        sender.id for sender in _email_integrations(team_id, sender_ids).select_for_update() if _is_unverified(sender)
    )


def unverified_sender_domains(*, team_id: int, sender_ids: frozenset[int]) -> dict[int, str]:
    """The domain of each sender among ``sender_ids`` that exists and is not verified yet, keyed by sender id."""
    if not sender_ids:
        return {}
    return {
        sender.id: _sender_domain(sender.config or {})
        for sender in _email_integrations(team_id, sender_ids)
        if _is_unverified(sender)
    }


def _sender_domain(config: dict) -> str:
    return config.get("domain") or str(config.get("email") or "").rpartition("@")[2]


def waiting_flows_using(*, team_id: int, sender_ids: frozenset[int]) -> list[UUID]:
    """The waiting workflows of the team that send email from any of ``sender_ids``."""
    if not sender_ids:
        return []
    waiting = HogFlow.objects.filter(team_id=team_id, status=HogFlow.State.WAITING_FOR_DOMAIN).only("id", "actions")
    return [flow.id for flow in waiting.iterator() if email_senders_of(flow) & sender_ids]
