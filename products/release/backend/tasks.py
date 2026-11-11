from django.db import transaction

from celery import shared_task

from .facade import api


@shared_task(ignore_result=True)
def create_release_for_new_flag(flag_id: int, team_id: int) -> None:
    api.create_release_for_new_flag(flag_id, team_id)


def queue_release_for_new_flag(flag_id: int, team_id: int) -> None:
    transaction.on_commit(lambda: create_release_for_new_flag.delay(flag_id, team_id))
