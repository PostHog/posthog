from celery import shared_task


@shared_task(ignore_result=True)
def process_due_reminders() -> None:
    from products.reminders.backend.firing import process_due_reminders as _process  # noqa: PLC0415

    _process()
