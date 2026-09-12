from datetime import datetime, timedelta

from django.utils import timezone

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

from products.cdp.backend.facade.models import HogFunction, HogFunctionType
from products.feature_flags.backend.flag_status import FeatureFlagStatus, FeatureFlagStatusChecker, filter_stale_flags
from products.feature_flags.backend.models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

# Emitted once per stale period of a flag
STALE_FLAG_EVENT = "$feature_flag_stale"

EVIDENCE_NOT_CALLED_RECENTLY = "not_called_recently"
EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA = "fully_rolled_out_without_usage_data"

# Evidence date of the last notice, per flag. A flag that gets called again has a newer evidence date
# and is reported again once it goes stale.
_NOTIFIED_KEY_PREFIX = "posthog:feature_flags:stale_notified:"
_NOTIFIED_KEY_TTL = timedelta(days=180)


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


def notify_stale_flags_for_team(team_id: int, now: datetime | None = None) -> int:
    """Emit STALE_FLAG_EVENT for each flag that went stale since it was last reported. Returns the count."""
    now = now or timezone.now()
    redis = get_client()
    notified = 0

    candidates = filter_stale_flags(
        FeatureFlag.objects.filter(team_id=team_id, active=True, archived=False).exclude(is_remote_configuration=True)
    )
    for flag in candidates:
        checker = FeatureFlagStatusChecker(feature_flag=flag)
        status, reason = checker.get_status()
        # The per-flag checker is what the flag page shows; the two disagree on some legacy shapes
        if status != FeatureFlagStatus.STALE:
            continue

        evidence_date = flag.last_called_at or flag.created_at
        key = f"{_NOTIFIED_KEY_PREFIX}{flag.id}"
        if _already_notified(redis.get(key), evidence_date):
            continue

        try:
            produce_internal_event(
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
                        "evidence_class": (
                            EVIDENCE_NOT_CALLED_RECENTLY
                            if flag.last_called_at is not None
                            else EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA
                        ),
                        "days_since_evidence": (now - evidence_date).days,
                        "last_called_at": flag.last_called_at.isoformat() if flag.last_called_at else None,
                    },
                ),
            )
        except Exception as e:
            # Not marked as notified, so it is retried on the next run
            logger.exception("stale_flag_notification_failed", team_id=team_id, flag_id=flag.id, error=str(e))
            capture_exception(e, additional_properties={"team_id": team_id, "flag_id": flag.id})
            continue

        redis.set(key, evidence_date.isoformat(), ex=_NOTIFIED_KEY_TTL)
        notified += 1

    if notified:
        logger.info("stale_flags_notified", team_id=team_id, count=notified)
    return notified


def _already_notified(stored: bytes | str | None, evidence_date: datetime) -> bool:
    if stored is None:
        return False
    stored_iso = stored.decode() if isinstance(stored, bytes) else stored
    try:
        return datetime.fromisoformat(stored_iso) >= evidence_date
    except ValueError:
        return False
