"""Celery beat schedules for foundry.

Registered centrally in ``posthog/tasks/scheduled.py`` (``setup_periodic_tasks``), which
is where every product's periodic tasks are wired — product ``schedules.py`` files are
not auto-collected. The crontab lives here so the product owns its schedule definition;
``scheduled.py`` imports it (same pattern as ``products/stamphog/backend/tasks/schedules.py``).
"""

from celery.schedules import crontab

# Every 15 minutes: frequent enough that a short-min_hours dev-stack/E2E ramp sees a
# verdict.proposed without a long wait, cheap enough for production (one query per
# exposed bet, at most).
SCOUT_SWEEP_CRONTAB = crontab(minute="*/15")
