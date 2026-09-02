"""Celery wiring for docs: the tasks core schedules, re-exported for ``posthog/tasks/scheduled.py``."""

from ..tasks.schedules import DOC_WATCH_CHECK_CRONTAB
from ..tasks.tasks import check_doc_watches_task, sync_context_doc_task

__all__ = ["DOC_WATCH_CHECK_CRONTAB", "check_doc_watches_task", "sync_context_doc_task"]
