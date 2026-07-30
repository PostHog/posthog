"""Celery beat schedules for stamphog.

The daily merged-PR digest fan-out (``send_daily_digests``) is registered centrally in
``posthog/tasks/scheduled.py`` (``setup_periodic_tasks``), which is where every product's periodic
tasks are wired — product ``schedules.py`` files are not auto-collected. The crontab lives here so
the product owns its schedule definition; scheduled.py imports it.
"""

from celery.schedules import crontab

# Weekday digest fan-out, 07:00 UTC Mon-Fri. No weekend runs: Monday's digest covers
# everything since Friday's slot.
DAILY_DIGEST_CRONTAB = crontab(hour="7", minute="0", day_of_week="mon-fri")
