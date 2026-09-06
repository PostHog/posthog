"""Exact (model, effort) allowlist for product `wizard`.

The wizard CLI dispatches a closed set of models, each at a fixed set of reasoning efforts. Any
other pair on this product is a lifted token driving a general coding agent, so the check is
exact on both axes and blocks everything it does not name. The list itself lives in the
`wizard-gateway-model-allowlist` flag payload so a wizard release that adds a model is a flag
edit, not a gateway deploy; the settings table is the answer while the flag is off or unreachable.
"""

from __future__ import annotations

import json
from typing import Any, Final

import structlog

from llm_gateway.api.handler import effort_from_output_config, effort_from_reasoning, effort_from_reasoning_effort
from llm_gateway.bedrock import get_bedrock_model_access_candidates, get_bedrock_region_name
from llm_gateway.config import get_settings
from llm_gateway.flags import evaluate_flag_payload

logger = structlog.get_logger(__name__)

WIZARD_MODEL_ALLOWLIST_FLAG: Final[str] = "wizard-gateway-model-allowlist"
# The allowlist is one table for every caller, so the flag is evaluated for a fixed identity
# and its payload cached once rather than per user.
_FLAG_DISTINCT_ID: Final[str] = "llm-gateway"
# Payload value naming "a request with no effort parameter".
NO_EFFORT: Final[str] = "none"
# pi sends the provider-prefixed id for OpenAI models; the payload names the bare model.
_STRIPPED_PREFIXES: Final[tuple[str, ...]] = ("openai/",)

Allowlist = dict[str, frozenset[str]]


def normalize_model(model: str) -> str:
    normalized = model.strip().lower()
    for prefix in _STRIPPED_PREFIXES:
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


def parse_allowlist(raw: object) -> Allowlist | None:
    """A payload of `{model: [effort, ...]}`, or None when the shape is unusable.

    Entries are dropped one at a time so a typo in one model cannot unblock or block the rest:
    a model with no valid effort is kept with an empty set, which allows nothing for it.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            logger.warning("wizard_allowlist_payload_not_json")
            return None
    if not isinstance(raw, dict):
        return None
    allowlist: Allowlist = {}
    for model, efforts in raw.items():
        if not isinstance(model, str) or not model.strip():
            continue
        if not isinstance(efforts, list):
            logger.warning("wizard_allowlist_efforts_not_list", model=model)
            efforts = []
        allowlist[normalize_model(model)] = frozenset(
            effort.strip().lower() for effort in efforts if isinstance(effort, str) and effort.strip()
        )
    return allowlist


async def resolve_allowlist() -> Allowlist:
    payload = await evaluate_flag_payload(WIZARD_MODEL_ALLOWLIST_FLAG, _FLAG_DISTINCT_ID)
    parsed = parse_allowlist(payload) if payload is not None else None
    if parsed is not None:
        return parsed
    if payload is not None:
        logger.warning("wizard_allowlist_payload_unusable", payload_type=type(payload).__name__)
    return parse_allowlist(get_settings().wizard_model_allowlist) or {}


def request_efforts(request_data: dict[str, Any] | None) -> frozenset[str]:
    """Every effort the body declares across the API shapes the gateway serves, lowercased.
    Empty means the request carries none."""
    if not request_data:
        return frozenset()
    found = {
        effort.lower()
        for effort in (
            effort_from_output_config(request_data),
            effort_from_reasoning_effort(request_data),
            effort_from_reasoning(request_data),
        )
        if effort is not None
    }
    return frozenset(found)


def check_wizard_model_access(
    model: str,
    efforts: frozenset[str],
    allowlist: Allowlist,
    provider: str | None = None,
) -> tuple[bool, str | None]:
    """(allowed, reason). Exact model match, then every declared effort must be listed for it."""
    candidates = {normalize_model(model)}
    if provider == "bedrock":
        region = get_bedrock_region_name(settings=get_settings())
        candidates |= {normalize_model(c) for c in get_bedrock_model_access_candidates(model, region_name=region)}
    matched = next((c for c in candidates if c in allowlist), None)
    if matched is None:
        return False, f"Model '{model}' is not available to the wizard."
    allowed_efforts = allowlist[matched]
    declared = efforts or frozenset({NO_EFFORT})
    if not declared <= allowed_efforts:
        return False, f"Effort '{', '.join(sorted(declared))}' is not available to the wizard for model '{model}'."
    return True, None
