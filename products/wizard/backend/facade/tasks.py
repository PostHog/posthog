"""Facade re-export for the wizard Celery task.

Core's beat schedule (``posthog/tasks/scheduled.py``) imports the task object and calls
``.s()`` on it, so the wiring crosses the boundary as an object, not data. Re-exporting
the task keeps that coupling at the facade boundary. Its ``name=`` is pinned in
``tasks/reconciliation.py``, so the registered task identity is independent of the import path.
"""

from products.wizard.backend.tasks.reconciliation import reconcile_wizard_runs

__all__ = ["reconcile_wizard_runs"]
