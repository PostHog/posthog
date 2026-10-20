"""Celery surface that core's beat wiring registers."""

from products.research_desk.backend.tasks.schedules import CALENDAR_SCOUT_CRONTAB, SOURCE_DISCOVERY_CRONTAB
from products.research_desk.backend.tasks.tasks import run_calendar_scout, run_source_discovery

__all__ = ["CALENDAR_SCOUT_CRONTAB", "SOURCE_DISCOVERY_CRONTAB", "run_calendar_scout", "run_source_discovery"]
