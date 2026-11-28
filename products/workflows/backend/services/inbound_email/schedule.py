from typing import Any

from celery.schedules import crontab

_TASKS = "products.workflows.backend.tasks.inbound_email"


def register_inbound_email_schedules(sender: Any, **kwargs: Any) -> None:
    """Connected to `beat_init` by the app config, so core's schedule list doesn't have to name this product.

    Beat has read its static schedule by the time `beat_init` fires, so the entries go straight into its scheduler.
    RedBeat keeps an entry added this way after it is removed here, until its `redbeat:<name>` key is deleted.
    """
    sender.scheduler.update_from_dict(
        {
            # Received email keeps for 30 days. A run deletes a bounded batch, so hourly keeps up with a backlog.
            "expire received email": {
                "task": f"{_TASKS}.delete_expired_received_emails_task",
                "schedule": crontab(hour="*", minute="23"),
                "options": {"expires": 50 * 60},
            },
            # A run checks a bounded batch of receiving domains, oldest check first.
            "check receiving domains": {
                "task": f"{_TASKS}.sweep_inbound_email_domains_task",
                "schedule": crontab(hour="*", minute="37"),
                "options": {"expires": 50 * 60},
            },
        }
    )
