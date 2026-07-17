"""
Facade re-exports for tasks access / usage gating.

``has_tasks_access`` gates whether a user may use the tasks/code product.
``code_access_required_response`` and ``cloud_usage_limit_response`` provide the HTTP-layer
responses used by user-triggered cloud execution paths. Presentation imports them from here rather
than reaching the internal ``access`` / ``logic.services.code_usage_gate`` modules directly.
"""

from products.tasks.backend.access import has_tasks_access
from products.tasks.backend.logic.services.code_usage_gate import (
    cloud_usage_limit_response,
    code_access_required_response,
)

__all__ = ["cloud_usage_limit_response", "code_access_required_response", "has_tasks_access"]
