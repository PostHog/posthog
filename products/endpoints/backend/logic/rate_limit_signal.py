"""Signals for endpoint run requests refused with a 429.

Every refusal increments ``posthog_endpoint_rate_limited_total`` (fleet view, no team label).
A ``endpoint rate limited`` analytics event carries the team, so refusals can be grouped
per team in the warehouse. The event is sent at most once per (team, endpoint, reason)
per window, so a team retrying in a tight loop does not flood the event stream.
"""

from enum import StrEnum

from django.core.cache import cache

import structlog
import posthoganalytics

from products.endpoints.backend.metrics import ENDPOINT_RATE_LIMITED_TOTAL

logger = structlog.get_logger(__name__)

RATE_LIMITED_EVENT = "endpoint rate limited"
RATE_LIMITED_EVENT_WINDOW_SECONDS = 60
_DEDUP_CACHE_KEY = "endpoint_rate_limited_event:{team_id}:{endpoint_name}:{reason}"


class EndpointRateLimitReason(StrEnum):
    MATERIALIZED_RATE = "materialized_rate"
    INLINE_RATE = "inline_rate"
    CONCURRENCY = "concurrency"
    READ_BUDGET = "read_budget"


def record_endpoint_rate_limited(
    *,
    team_id: int | None,
    endpoint_name: str | None,
    version: int | None,
    reason: EndpointRateLimitReason,
    scope: str,
) -> None:
    """Count a 429 and send the deduplicated per-team event. Never raises: this runs on the request path."""
    try:
        ENDPOINT_RATE_LIMITED_TOTAL.labels(scope=scope, reason=reason.value).inc()
    except Exception:
        logger.warning("endpoint_rate_limited_metric_failed", exc_info=True)

    if team_id is None or not endpoint_name:
        return

    try:
        dedup_key = _DEDUP_CACHE_KEY.format(team_id=team_id, endpoint_name=endpoint_name, reason=reason.value)
        if not cache.add(dedup_key, 1, timeout=RATE_LIMITED_EVENT_WINDOW_SECONDS):
            return
        # The SDK only enqueues here; a background thread delivers the batch.
        posthoganalytics.capture(
            distinct_id=f"team_{team_id}",
            event=RATE_LIMITED_EVENT,
            properties={
                "team_id": team_id,
                "endpoint_name": endpoint_name,
                "endpoint_version": version,
                "reason": reason.value,
                "scope": scope,
                "$process_person_profile": False,
            },
        )
    except Exception:
        logger.warning("endpoint_rate_limited_event_failed", exc_info=True)
