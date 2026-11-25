from django.db.models import Q

from celery import shared_task


@shared_task(ignore_result=True)
def schedule_delegated_task_recovery() -> None:
    from products.meep.backend.models import BoardRun, ChatTurn, ChildWait  # noqa: PLC0415

    pending = BoardRun.objects.filter(
        Q(finished=False) | Q(notified=False), parent_turn__isnull=False, topic__deleted=False, topic__archived=False
    )
    waiting = ChildWait.objects.filter(status="waiting")
    delivering = ChatTurn.objects.filter(
        target_message_id__isnull=False, finished_at=None, topic__deleted=False, topic__archived=False
    )
    fields = ("topic__team_id", "topic_id")
    topics = pending.values_list(*fields).union(
        waiting.values_list(*fields), delivering.order_by().values_list(*fields)
    )
    for team_id, topic_id in topics.iterator():
        reconcile_topic_tasks.delay(team_id, str(topic_id))


@shared_task(ignore_result=True)
def reconcile_topic_tasks(team_id: int, topic_id: str) -> None:
    from products.meep.backend.board import finish_board  # noqa: PLC0415
    from products.meep.backend.chat import finish_turn  # noqa: PLC0415
    from products.meep.backend.delegation import reconcile_notification, reconcile_wait  # noqa: PLC0415
    from products.meep.backend.models import Topic  # noqa: PLC0415

    topic = Topic.objects.for_team(team_id).filter(pk=topic_id).first()
    if topic is None:
        return
    if topic.archived or topic.deleted:
        topic.child_waits.filter(status="waiting").update(status="cancelled")
        topic.board_runs.filter(parent_turn__isnull=False, notified=False).update(notified=True)
        return
    children = topic.board_runs.filter(parent_turn__isnull=False)
    for run_id in children.filter(finished=False).values_list("run_id", flat=True):
        finish_board(run_id, team_id)
    for run_id in topic.turns.filter(finished_at=None).values_list("run_id", flat=True):
        finish_turn(run_id, team_id)
    for wait_id in topic.child_waits.filter(status="waiting").values_list("pk", flat=True):
        reconcile_wait(wait_id)
    for job_id in children.filter(finished=True, notified=False).values_list("pk", flat=True):
        reconcile_notification(job_id)
