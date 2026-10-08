"""Pauses the scouts of a turned-off scanner after each one has run once more.

That last run reports on what the scanner saw before it stopped. Without the pause, the scouts keep
running on a scanner that adds nothing new, and every run costs the customer.
"""

import datetime as dt

from django.utils import timezone

import structlog

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.scout_source import SCOUT_SOURCE_PRODUCT
from products.signals.backend.facade import api as signals_facade

logger = structlog.get_logger(__name__)

# Past the longest scout schedule (30 days). A scout that has not run by then is held by something
# else, such as a system pause, so the scanner stops waiting for it.
WIND_DOWN_GIVE_UP_AFTER = dt.timedelta(days=31)
WIND_DOWN_MAX_PER_RUN = 200


def pause_scouts_after_final_run() -> int:
    """Pause each scout whose scanner was turned off before its newest run started, and return how many.

    A scanner leaves the wind-down once none of its scouts waits for a final run. A person can then
    turn a scout back on and keep it.
    """
    cutoff = timezone.now() - WIND_DOWN_GIVE_UP_AFTER
    pending = list(
        ReplayScanner.objects.filter(enabled=False, scout_wind_down_since__isnull=False)
        .order_by("scout_wind_down_since")
        .values_list("id", "team_id", "scout_wind_down_since")[:WIND_DOWN_MAX_PER_RUN]
    )
    paused = 0
    for scanner_id, team_id, since in pending:
        waiting = False
        if since >= cutoff:
            for scout in signals_facade.scouts_for_source(team_id, SCOUT_SOURCE_PRODUCT, str(scanner_id)):
                if not scout.enabled:
                    continue
                if scout.last_run_started_at is None or scout.last_run_started_at < since:
                    waiting = True
                elif signals_facade.update_scout_for_source(
                    team_id, SCOUT_SOURCE_PRODUCT, scout.config_id, enabled=False
                ):
                    paused += 1
        if not waiting:
            # Matched on the stamp, so a scanner turned on and off again meanwhile keeps its new wind-down.
            ReplayScanner.objects.filter(pk=scanner_id, enabled=False, scout_wind_down_since=since).update(
                scout_wind_down_since=None
            )
    if paused:
        logger.info("replay_vision.scout_wind_down.scouts_paused", paused=paused)
    return paused
