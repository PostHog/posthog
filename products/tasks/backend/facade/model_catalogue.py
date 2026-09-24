"""Facade re-exports for the live model catalogue a run picker offers.

Kept separate from `facade/run_config.py` because that one is deliberately
framework-free — pure enums and parse helpers — while this reaches the LLM gateway over
the network and caches through Django. Cross-product callers (the Slack app's App Home
picker and model-override classifier) import from here rather than reaching into
`logic/services/`.
"""

from products.tasks.backend.logic.services.model_catalogue import (
    COST_BASELINE_MODEL,
    REASONING_EFFORT_DISPLAY_NAMES,
    RUNTIME_ADAPTER_DISPLAY_NAMES,
    TASK_RUN_GATEWAY_PRODUCT,
    GatewayModel,
    ModelChoice,
    RuntimeGroup,
    available_model_choices,
    catalog_model_choices,
    display_name_for_model,
    filter_unsupported_effort,
    group_by_runtime,
    label_for,
    offered_model_choices,
    runtime_adapter_for,
)

__all__ = [
    "COST_BASELINE_MODEL",
    "REASONING_EFFORT_DISPLAY_NAMES",
    "RUNTIME_ADAPTER_DISPLAY_NAMES",
    "TASK_RUN_GATEWAY_PRODUCT",
    "GatewayModel",
    "ModelChoice",
    "RuntimeGroup",
    "available_model_choices",
    "catalog_model_choices",
    "display_name_for_model",
    "filter_unsupported_effort",
    "group_by_runtime",
    "label_for",
    "offered_model_choices",
    "runtime_adapter_for",
]
