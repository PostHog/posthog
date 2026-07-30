import structlog
import posthoganalytics

from posthog.event_usage import groups
from posthog.models import Team
from posthog.redis import get_async_client

logger = structlog.get_logger(__name__)

# Issue lifecycle signals are emitted one-per-issue at weight 1.0, which on its own is enough to
# trigger report generation. A bad deploy can create hundreds of issues in minutes, so without a
# ceiling a single error storm fans out 1:1 into signal emissions and LLM reports.
MAX_LIFECYCLE_SIGNALS_PER_HOUR = 20
_WINDOW_SECONDS = 3600


def _counter_key(team_id: int, source_type: str) -> str:
    return f"error_tracking/lifecycle_signal_budget/{team_id}/{source_type}"


def _decision_key(team_id: int, source_type: str, dedupe_key: str) -> str:
    return f"error_tracking/lifecycle_signal_budget/{team_id}/{source_type}/decision/{dedupe_key}"


async def consume_lifecycle_signal_budget(team: Team, source_type: str, dedupe_key: str) -> bool:
    """Reserve one emission from the team's hourly budget for this lifecycle source type.

    Returns False when the budget is exhausted and the caller should skip emitting. The window is
    anchored on the first emission rather than the wall clock, so a burst can't straddle two
    calendar buckets and emit twice the cap. The decision is cached per `dedupe_key` so an activity
    retry re-reads its own verdict instead of burning a second slot. Fails open — a Redis outage
    shouldn't mute signals.
    """
    try:
        redis = get_async_client()
        decision_key = _decision_key(team.id, source_type, dedupe_key)
        cached = await redis.get(decision_key)
        if cached is not None:
            return cached in (b"1", "1")

        counter_key = _counter_key(team.id, source_type)
        used = await redis.incr(counter_key)
        if used == 1:
            await redis.expire(counter_key, _WINDOW_SECONDS)
        allowed = used <= MAX_LIFECYCLE_SIGNALS_PER_HOUR
        await redis.set(decision_key, b"1" if allowed else b"0", ex=_WINDOW_SECONDS)
    except Exception:
        logger.exception(
            "Failed to check the error tracking lifecycle signal budget",
            team_id=team.id,
            source_type=source_type,
        )
        return True

    if allowed:
        return True

    logger.warning(
        "Throttled an error tracking lifecycle signal",
        team_id=team.id,
        source_type=source_type,
        signals_in_window=used,
        cap=MAX_LIFECYCLE_SIGNALS_PER_HOUR,
    )
    try:
        posthoganalytics.capture(
            event="signal_emission_throttled",
            distinct_id=str(team.uuid),
            properties={
                "source_product": "error_tracking",
                "source_type": source_type,
                "signals_in_window": used,
                "cap": MAX_LIFECYCLE_SIGNALS_PER_HOUR,
            },
            groups=groups(team=team),
        )
    except Exception:
        logger.exception(
            "Failed to capture signal_emission_throttled event",
            team_id=team.id,
            source_type=source_type,
        )
    return False
