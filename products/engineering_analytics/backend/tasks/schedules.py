"""Celery beat schedules for engineering_analytics.

Not auto-collected: posthog/tasks/scheduled.py imports these constants through the facade
and registers them explicitly.
"""

from celery.schedules import crontab

TEST_CENSUS_CRONTAB = crontab(hour="6", minute="45")
