"""Stamphog Celery tasks.

Import the task-defining submodules here so Celery's ``autodiscover_tasks`` (which imports the
app's ``tasks`` package) registers every ``@shared_task`` on workers and beat.
"""

from products.stamphog.backend.tasks import digest, tasks  # noqa: F401
