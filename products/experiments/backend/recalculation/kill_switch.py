import structlog

from posthog.models.instance_setting import get_instance_setting

logger = structlog.get_logger(__name__)

RECALCULATION_ENABLED_SETTING = "EXPERIMENTS_RECALCULATION_ENABLED"


def recalculation_enabled() -> bool:
    try:
        return bool(get_instance_setting(RECALCULATION_ENABLED_SETTING))
    except Exception:
        # Fail open: a read error means Postgres is failing, and then no run row can be written either.
        logger.warning("recalculation_enabled_read_failed", exc_info=True)
        return True
