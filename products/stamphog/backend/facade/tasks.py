"""Facade re-export for the stamphog Celery surface.

Core's central beat wiring (``posthog/tasks/scheduled.py``) registers the daily digest fan-out
from here rather than reaching into the product's internals, and review_hog's inbox trigger
queues the initial self-driving PR review from here. Lives apart from ``api.py`` so the task
modules' heavy imports (GitHub client, temporal client) stay off that module, which review_hog's
settings serializer imports on every request.
"""

from products.stamphog.backend.tasks.digest import send_daily_digests
from products.stamphog.backend.tasks.schedules import DAILY_DIGEST_CRONTAB
from products.stamphog.backend.tasks.tasks import (
    process_inbox_pr_review,
    process_installation_event,
    process_pull_request_event,
)

__all__ = [
    "DAILY_DIGEST_CRONTAB",
    "process_installation_event",
    "process_pull_request_event",
    "queue_inbox_pr_review",
    "send_daily_digests",
]


def queue_inbox_pr_review(
    *,
    team_id: int,
    pr_url: str,
    repository: str,
    acting_user_id: int,
    signal_report_id: str,
    task_run_id: str,
) -> None:
    """Queue the first hosted Stamphog review of a self-driving inbox PR, without waiting for it.

    Called by review_hog's inbox trigger, which has already found an assigned reviewer with the
    ``stamphog_review_inbox_prs`` toggle on. ``repository`` is the linked task's own repo, and the
    PR must be in it, because the task-to-PR link this rides on (``TaskRun.output.pr_url``) is
    writable through the task-run API. The Celery task does the rest: resolve a synced and enabled
    repo config (no-op without one), fetch the PR, re-check that the App machine user authored it,
    create the run with inbox provenance, start the workflow. That keeps GitHub and the product DB
    off the caller's save path.
    """
    process_inbox_pr_review.delay(
        team_id=team_id,
        pr_url=pr_url,
        repository=repository,
        acting_user_id=acting_user_id,
        signal_report_id=signal_report_id,
        task_run_id=task_run_id,
    )
