from django.db import DatabaseError, transaction

from celery import shared_task

from .facade import api

OWNERSHIP_DELAY = 60


@shared_task(ignore_result=True, autoretry_for=(DatabaseError,), retry_backoff=True, max_retries=3)
def create_release_for_new_flag(flag_id: int, team_id: int) -> None:
    api.create_release_for_new_flag(flag_id, team_id)


def queue_release_for_new_flag(flag_id: int, team_id: int) -> None:
    transaction.on_commit(
        lambda: create_release_for_new_flag.apply_async((flag_id, team_id), countdown=OWNERSHIP_DELAY)
    )
