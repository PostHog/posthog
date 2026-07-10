from celery import shared_task


@shared_task(ignore_result=True)
def mark_stale_pulse_briefs_failed() -> None:
    from products.pulse.backend.reaper import mark_stale_briefs_failed  # noqa: PLC0415

    mark_stale_briefs_failed()
