"""Celery beat schedules for research_desk, wired in posthog/tasks/scheduled.py."""

from celery.schedules import crontab

CALENDAR_SCOUT_CRONTAB = crontab(minute="*/15")
SOURCE_DISCOVERY_CRONTAB = crontab(hour="6", minute="20")
