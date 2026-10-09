"""Facade for the inference choice of a run: PostHog credits or the user's plan.

The Cloud Agents product calls ``resolve_inference`` before it creates or resumes a task, then
passes ``InferenceDecision.run_state_updates`` as ``inference_state`` to
``facade.cloud_agents``. Billing code calls ``inference_billing_for_state`` on a run's state.
"""

from products.tasks.backend.logic.model_access import InferenceBilling, inference_billing_for_state
from products.tasks.backend.logic.services.inference_resolution import (
    ClaudeSubscriptionMissing,
    InferenceDecision,
    InferenceRequest,
    InferenceUnavailable,
    InferenceUnavailableCode,
    RunInferenceCredential,
    resolve_inference,
)

__all__ = [
    "InferenceBilling",
    "ClaudeSubscriptionMissing",
    "InferenceDecision",
    "InferenceRequest",
    "InferenceUnavailable",
    "InferenceUnavailableCode",
    "RunInferenceCredential",
    "inference_billing_for_state",
    "resolve_inference",
]
