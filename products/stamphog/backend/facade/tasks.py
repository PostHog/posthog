"""Facade re-export for the stamphog Celery beat surface.

Core's central beat wiring (``posthog/tasks/scheduled.py``) registers the daily digest fan-out
from here rather than reaching into the product's internals.
"""

from products.stamphog.backend.tasks.digest import send_daily_digests
from products.stamphog.backend.tasks.schedules import DAILY_DIGEST_CRONTAB

__all__ = ["DAILY_DIGEST_CRONTAB", "send_daily_digests"]
