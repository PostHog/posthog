"""Django app configuration for docs."""

from django.apps import AppConfig


class DocsConfig(AppConfig):
    name = "products.docs.backend"
    label = "docs"

    def ready(self) -> None:
        from products.tasks.backend.facade import signals  # noqa: PLC0415 — apps are not loaded at import time

        from . import receivers  # noqa: PLC0415 — same
        from .tasks import tasks as _celery_tasks  # noqa: F401, PLC0415 — registers the shared tasks

        signals.task_run_turn_finished.connect(receivers.on_task_run_turn_finished, dispatch_uid="docs_agent_turn")
