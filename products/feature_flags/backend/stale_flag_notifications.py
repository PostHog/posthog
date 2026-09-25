from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

import structlog

from posthog.cdp.internal_events import InternalEventEvent, flush_internal_events_producer, produce_internal_event
from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.client import ProduceResult
from posthog.redis import get_client

from products.cdp.backend.facade.models import HogFunction, HogFunctionType
from products.feature_flags.backend.flag_status import (
    FeatureFlagStatus,
    FeatureFlagStatusChecker,
    filter_stale_flags,
    stale_evidence,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

# Emitted once per stale period of a flag
STALE_FLAG_EVENT = "$feature_flag_stale"

# A team's first run, or a batch of flags going stale on the same day, can produce far more events
# than a chat channel takes at once: Slack accepts about one post per second per channel and CDP
# gives up on a 429 within seconds. The rest of the backlog goes out on the following runs.
MAX_NOTIFICATIONS_PER_TEAM_PER_RUN = 10

_FLUSH_TIMEOUT_SECONDS = 30.0

# Evidence date of the last notice, per flag. A flag that gets called again has a newer evidence date
# and is reported again once it goes stale. The TTL is refreshed on every run while the flag stays
# stale, so the marker outlives any stale period and only expires once the flag is no longer reported.
_NOTIFIED_KEY_PREFIX = "posthog:feature_flags:stale_notified:"
_NOTIFIED_KEY_TTL = timedelta(days=180)


def stale_notified_key(flag_id: int) -> str:
    return f"{_NOTIFIED_KEY_PREFIX}{flag_id}"


def teams_subscribed_to_stale_flags() -> list[int]:
    """Teams with an enabled destination for STALE_FLAG_EVENT. Only these are evaluated."""
    return list(
        HogFunction.objects.filter(
            type=HogFunctionType.INTERNAL_DESTINATION,
            enabled=True,
            deleted=False,
            filters__events__contains=[{"id": STALE_FLAG_EVENT}],
        )
        .values_list("team_id", flat=True)
        .distinct()
    )


@dataclass
class _PendingNotice:
    flag: FeatureFlag
    key: str
    evidence_date: datetime
    result: ProduceResult


def notify_stale_flags_for_team(team_id: int) -> int:
    """Emit STALE_FLAG_EVENT for each flag that went stale since it was last reported. Returns the count."""
    now = timezone.now()
    redis = get_client()

    # Ordered so a backlog larger than the cap goes out in the same order on every run
    candidates = filter_stale_flags(
        FeatureFlag.objects.filter(team_id=team_id, active=True, archived=False).exclude(is_remote_configuration=True)
    ).order_by("id")
    pending: list[_PendingNotice] = []
    for flag in candidates:
        checker = FeatureFlagStatusChecker(feature_flag=flag)
        status, reason = checker.get_status()
        # The checker's status and reason are what the flag page shows, so it has the final say.
        # filter_stale_flags only narrows the query.
        if status != FeatureFlagStatus.STALE:
            continue

        evidence_class, evidence_date = stale_evidence(flag)
        key = stale_notified_key(flag.id)
        if _already_notified(redis.get(key), evidence_date):
            redis.expire(key, _NOTIFIED_KEY_TTL)
            continue
        if len(pending) >= MAX_NOTIFICATIONS_PER_TEAM_PER_RUN:
            continue

        try:
            result = produce_internal_event(
                team_id=team_id,
                event=InternalEventEvent(
                    event=STALE_FLAG_EVENT,
                    distinct_id=f"team_{team_id}",
                    properties={
                        # String, like the activity log's item_id, so a per-flag destination can filter on it
                        "flag_id": str(flag.id),
                        "flag_key": flag.key,
                        "flag_name": (flag.name or "")[:500],
                        "reason": reason,
                        "evidence_class": evidence_class,
                        "days_since_evidence": (now - evidence_date).days,
                        "last_called_at": flag.last_called_at.isoformat() if flag.last_called_at else None,
                    },
                ),
            )
        except Exception as e:
            _report_failure(e, team_id, flag.id)
            continue
        pending.append(_PendingNotice(flag=flag, key=key, evidence_date=evidence_date, result=result))

    # The producer only queues the event; delivery is known once the producer has flushed. A flag is
    # marked as notified only after its event was delivered, so a lost event is retried on the next run.
    if pending:
        _flush(team_id)
    notified = 0
    for notice in pending:
        try:
            notice.result.get(timeout=0)
        except Exception as e:
            _report_failure(e, team_id, notice.flag.id)
            continue
        redis.set(notice.key, notice.evidence_date.isoformat(), ex=_NOTIFIED_KEY_TTL)
        notified += 1

    if notified:
        logger.info("stale_flags_notified", team_id=team_id, count=notified)
    return notified


def _flush(team_id: int) -> None:
    try:
        remaining = flush_internal_events_producer(_FLUSH_TIMEOUT_SECONDS)
        if remaining:
            logger.warning("stale_flag_notifications_flush_timed_out", team_id=team_id, remaining=remaining)
    except Exception as e:
        # Every pending result then reads as undelivered
        logger.exception("stale_flag_notifications_flush_failed", team_id=team_id, error=str(e))
        capture_exception(e, additional_properties={"team_id": team_id})


def _report_failure(error: Exception, team_id: int, flag_id: int) -> None:
    logger.exception("stale_flag_notification_failed", team_id=team_id, flag_id=flag_id, error=str(error))
    capture_exception(error, additional_properties={"team_id": team_id, "flag_id": flag_id})


def _already_notified(stored: bytes | str | None, evidence_date: datetime) -> bool:
    if stored is None:
        return False
    stored_iso = stored.decode() if isinstance(stored, bytes) else stored
    try:
        return datetime.fromisoformat(stored_iso) >= evidence_date
    except ValueError:
        return False
