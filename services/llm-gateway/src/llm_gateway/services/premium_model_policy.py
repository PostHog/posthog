from __future__ import annotations

from llm_gateway.bedrock import ANTHROPIC_TO_BEDROCK_MODEL_MAP
from llm_gateway.config import get_settings
from llm_gateway.products.config import get_product_config
from llm_gateway.services.plan_resolver import is_usage_based_plan


def is_premium_model_gate_active(product: str) -> bool:
    config = get_product_config(product)
    settings = get_settings()
    return bool(config and config.premium_models_gated and settings.premium_model_gate_enabled)


def _premium_model_prefixes() -> tuple[str, ...]:
    prefixes: set[str] = set()
    for configured_model in get_settings().premium_models:
        model = configured_model.strip().lower()
        if not model:
            continue
        prefixes.add(model)
        region_map = ANTHROPIC_TO_BEDROCK_MODEL_MAP.get(model)
        if region_map:
            prefixes.update(alias.lower() for alias in region_map.values())
    return tuple(prefixes)


def is_model_allowed_by_premium_policy(product: str, model: str | None, plan_key: str | None) -> bool:
    if not is_premium_model_gate_active(product) or not model:
        return True

    normalized_model = model.lower()
    if not normalized_model.startswith(_premium_model_prefixes()):
        return True

    return is_usage_based_plan(plan_key)
