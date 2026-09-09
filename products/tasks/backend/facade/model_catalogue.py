"""Facade re-exports for the live model catalogue a run picker offers.

Kept separate from `facade/run_config.py` because that one is deliberately
framework-free — pure enums and parse helpers — while this reaches the LLM gateway over
the network and caches through Django. Cross-product callers (the Slack app's App Home
picker and model-override classifier) import from here rather than reaching into
`logic/services/`.
"""

from products.tasks.backend.logic.services.model_catalogue import (
    REASONING_EFFORT_DISPLAY_NAMES,
    RUNTIME_ADAPTER_DISPLAY_NAMES,
    TASK_RUN_GATEWAY_PRODUCT,
    GatewayModel,
    ModelChoice,
    RuntimeGroup,
    available_model_choices,
    filter_unsupported_effort,
    format_model_id,
    group_by_runtime,
    label_for,
    runtime_adapter_for,
)

__all__ = [
    "REASONING_EFFORT_DISPLAY_NAMES",
    "RUNTIME_ADAPTER_DISPLAY_NAMES",
    "TASK_RUN_GATEWAY_PRODUCT",
    "GatewayModel",
    "ModelChoice",
    "RuntimeGroup",
    "available_model_choices",
    "filter_unsupported_effort",
    "format_model_id",
    "group_by_runtime",
    "label_for",
    "runtime_adapter_for",
]
