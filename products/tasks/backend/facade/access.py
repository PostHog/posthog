"""
Facade re-exports for tasks access checks.

``has_tasks_access`` reports Desktop waitlist access (the `tasks` flag or a redeemed invite) so
clients can gate their own UI — the backend does not enforce it on task execution.
``has_loops_access`` gates Loops on its own `loops` flag (see docs/LOOPS.md Rollout).

Deliberately light: asking whether a user has access is the one thing this module does, so it
stays importable without pulling in the HTTP layer. The 429 helpers that meter cloud execution
live in ``facade.usage_gating``.
"""

from products.tasks.backend.access import has_loops_access, has_tasks_access

__all__ = [
    "has_loops_access",
    "has_tasks_access",
]
