"""
Facade re-exports for tasks access / usage gating.

``has_tasks_access`` reports Desktop waitlist access (the `tasks` flag or a redeemed invite) so
clients can gate their own UI — the backend does not enforce it on task execution.
``has_loops_access`` gates Loops on its own `loops` flag (see docs/LOOPS.md Rollout).
``usage_limit_response`` provides the HTTP-layer 429 that meters cloud execution paths.
Presentation imports it from here rather than reaching the internal ``access`` /
``logic.services.code_usage_gate`` modules directly.
"""

from products.tasks.backend.access import has_loops_access, has_tasks_access
from products.tasks.backend.logic.services.code_usage_gate import usage_limit_response

__all__ = ["has_loops_access", "has_tasks_access", "usage_limit_response"]
