from django.db import transaction

from celery import shared_task

from ..facade import api

OWNERSHIP_DELAY = 60


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def create_release_for_new_flag(flag_id: int, team_id: int) -> None:
    api.create_release_for_new_flag(flag_id, team_id)


def _dispatch_if_adopted(flag_id: int, team_id: int) -> None:
    if api.project_uses_releases(team_id):
        create_release_for_new_flag.apply_async((flag_id, team_id), countdown=OWNERSHIP_DELAY)


def queue_release_for_new_flag(flag_id: int, team_id: int) -> None:
    transaction.on_commit(lambda: _dispatch_if_adopted(flag_id, team_id))
