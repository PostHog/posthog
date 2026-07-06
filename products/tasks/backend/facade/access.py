"""
Facade re-exports for tasks access / usage gating.

``has_tasks_access`` gates whether a user may use the tasks/code product.
``cloud_usage_limit_response`` returns a structured 429 ``Response`` when the team is over
its posthog_code usage limit (or ``None`` to proceed) — it is HTTP-layer Response wiring the
``run``/``start`` endpoints call directly. Presentation imports both from here rather than
reaching the internal ``access`` / ``logic.services.code_usage_gate`` modules directly.
"""

from products.tasks.backend.access import has_tasks_access
from products.tasks.backend.logic.services.code_usage_gate import cloud_usage_limit_response

__all__ = ["cloud_usage_limit_response", "has_tasks_access"]
