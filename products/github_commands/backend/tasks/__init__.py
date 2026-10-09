"""GitHub commands Celery tasks.

Import the task-defining submodules here so Celery's ``autodiscover_tasks`` (which imports the
app's ``tasks`` package) registers every ``@shared_task`` on workers.
"""

from products.github_commands.backend.tasks import tasks  # noqa: F401
