from celery import shared_task


@shared_task(ignore_result=True)
def send_thread_message_mention_dms(message_id: str, team_id: int) -> None:
    from products.tasks.backend.slack_mention_notifications import send_mention_dms_for_message  # noqa: PLC0415

    send_mention_dms_for_message(message_id, team_id)
