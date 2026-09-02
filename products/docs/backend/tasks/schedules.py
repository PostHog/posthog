"""Celery beat schedules for docs. Wired in ``posthog/tasks/scheduled.py``."""

from celery.schedules import crontab

# Watched hypotheses: due evidence checks run and scout reports land, four times an hour.
DOC_WATCH_CHECK_CRONTAB = crontab(minute="*/15")
