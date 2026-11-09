import structlog

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.signals.backend.facade import api as signals_facade
from products.signals.backend.facade.taxonomy import SignalSourceProduct

logger = structlog.get_logger(__name__)

# pinned: what a scout's config records as its owner. Signals stores it as `(source_product,
# source_id)`, where source_id is the scanner's id, and that pair is what ties a scout back to the
# scanner it watches — for finding them, for authorizing report reads, and for cleanup.
SCOUT_SOURCE_PRODUCT = SignalSourceProduct.REPLAY_VISION.value


def pause_scanner_scouts(scanner: ReplayScanner, *, tag: str | None = None) -> int:
    """Turn off the scanner's enabled scouts, optionally only those with `tag`, and return how many were turned off.

    A scanner that no longer runs adds no observations, so its scouts would only re-read unchanged data
    on the customer's bill and alert on it. They are not turned back on with the scanner: the person
    resumes them, because the scanner cannot tell which scouts they had paused on purpose.
    """
    paused = 0
    for scout in signals_facade.scouts_for_source(scanner.team_id, SCOUT_SOURCE_PRODUCT, str(scanner.id), tag=tag):
        if scout.enabled and signals_facade.update_scout_for_source(
            scanner.team_id, SCOUT_SOURCE_PRODUCT, scout.config_id, enabled=False
        ):
            paused += 1
    if paused:
        logger.info("replay_vision.scanner_scouts_paused", scanner_id=str(scanner.id), tag=tag, paused=paused)
    return paused
