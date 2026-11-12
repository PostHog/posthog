"""Not auto-collected: posthog/tasks/scheduled.py imports these through the facade and registers them."""

from celery.schedules import crontab

TEST_CENSUS_CRONTAB = crontab(hour="6", minute="45")
