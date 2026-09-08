from collections.abc import Callable

from django.db.models.signals import post_save

from products.tasks.backend.models import TaskRun


def connect_task_run_post_save(receiver: Callable[..., None], *, dispatch_uid: str) -> None:
    post_save.connect(receiver, sender=TaskRun, dispatch_uid=dispatch_uid)
