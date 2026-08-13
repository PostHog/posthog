"""Facade re-export for the legal_documents Celery tasks.

Core's beat schedule (``posthog/tasks/scheduled.py``) imports the reconciliation
task object and calls ``.s()`` on it, so the wiring crosses the boundary as an
object, not data. Re-exporting the tasks keeps that coupling at the facade
boundary. Each ``name=`` is pinned in ``tasks/tasks.py``, so the registered task
identity is independent of the import path.
"""

from ..tasks.tasks import archive_signed_legal_document_pdf, reconcile_pending_legal_documents

__all__ = ["archive_signed_legal_document_pdf", "reconcile_pending_legal_documents"]
