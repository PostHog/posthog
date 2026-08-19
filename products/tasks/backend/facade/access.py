"""
Facade re-exports for tasks access / usage gating.

``has_tasks_access`` reports Desktop waitlist access (the `tasks` flag or a redeemed invite).
``has_loops_access`` gates Loops on its own `loops` flag (see docs/LOOPS.md Rollout).
``code_access_required_response`` provides the HTTP-layer 403 that gates user-triggered cloud
execution on Desktop access; ``usage_limit_response`` provides the HTTP-layer 429 that meters
cloud execution paths. Presentation imports them from here rather than reaching the internal
``access`` / ``logic.services.code_usage_gate`` modules directly.
"""

from products.tasks.backend.access import has_loops_access, has_tasks_access
from products.tasks.backend.logic.services.code_usage_gate import (
    code_access_required_response,
    compute_quota_limit_response,
    usage_limit_response,
)

__all__ = [
    "code_access_required_response",
    "compute_quota_limit_response",
    "has_loops_access",
    "has_tasks_access",
    "usage_limit_response",
]
