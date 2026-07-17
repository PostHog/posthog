"""
Cross-region sync of the dogfood team's (team 2) flag definitions into EU's
HyperCache.

Every other team's `flag_definitions_hypercache` entry is rebuilt locally by
Django signals reading straight from Postgres (see local_evaluation.py). Team 2
-- PostHog's internal "self" team, used for our own dogfooded local evaluation
-- lives only in the US Postgres, so EU has no rows to build it from. Rather
than have every EU pod poll the US API directly (which HyperCache exists to
avoid), a single periodic task fetches team 2's flag definitions from the US
region's authenticated `/flags/definitions` endpoint and writes the result
straight into EU's HyperCache, so every EU pod still reads from the shared
cache with zero per-pod polling.

No-op on US, where team 2's HyperCache entry is already populated by the
normal signal-driven path.
"""

from django.conf import settings

import requests
import structlog
from posthoganalytics.request import US_INGESTION_ENDPOINT

from posthog.utils import capture_exception_throttled, get_instance_region

from products.feature_flags.backend.local_evaluation import flag_definitions_hypercache

logger = structlog.get_logger(__name__)

# PostHog's own internal "self" team, canonically team 2 (see _build_flag_provider
# in posthog/utils.py). Only its US Postgres rows are authoritative.
DOGFOOD_SELF_TEAM_ID = 2

_FLAGS_DEFINITIONS_PATH = "/flags/definitions"
_REQUEST_TIMEOUT_SECONDS = (3, 10)  # (connect, read)

# Throttle window for capturing a genuinely unexpected failure (bad JSON, an
# unexpected request error) to PostHog error tracking, shared across the 30s schedule
# so a sustained outage reports once per window instead of once per tick. Expected
# transient network blips (connection/timeout/proxy errors) are logged, not captured.
_SYNC_FAILURE_CAPTURE_THROTTLE_KEY = "cross_region_dogfood_flags_sync_capture_throttle"
_SYNC_FAILURE_CAPTURE_THROTTLE_TTL = 300  # seconds


def sync_cross_region_dogfood_flags() -> None:
    """Refresh team 2's flag-definitions HyperCache entry in EU from the US region.

    No-op outside EU or when the PSAK isn't configured. Uses the endpoint's ETag
    support: sends `If-None-Match` with the locally cached ETag, so an unchanged
    upstream is a 304 with no payload transferred and no local write.
    """
    # Defense in depth: the beat registration in scheduled.py is also EU-gated.
    # This keeps direct invocation (shell, tests) safe outside EU.
    if get_instance_region() != "EU":
        return

    token = settings.POSTHOG_FLAGS_PROJECT_SECRET_TOKEN
    if not token:
        logger.debug("cross_region_dogfood_flags_sync_no_token")
        return

    headers = {"Authorization": f"Bearer {token}"}
    local_etag = flag_definitions_hypercache.get_etag(DOGFOOD_SELF_TEAM_ID)
    if local_etag:
        headers["If-None-Match"] = f'"{local_etag}"'

    try:
        response = requests.get(
            f"{US_INGESTION_ENDPOINT}{_FLAGS_DEFINITIONS_PATH}",
            headers=headers,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except (requests.ConnectionError, requests.Timeout) as e:
        # Expected transient cross-region blips (proxy timeouts, connection resets).
        # ProxyError subclasses ConnectionError, so it's covered here. The best-effort
        # poll self-heals on the next 30s tick, so log without reporting to error tracking.
        logger.warning("cross_region_dogfood_flags_sync_request_failed", error=str(e))
        return
    except requests.RequestException as e:
        capture_exception_throttled(_SYNC_FAILURE_CAPTURE_THROTTLE_KEY, e, _SYNC_FAILURE_CAPTURE_THROTTLE_TTL)
        logger.warning("cross_region_dogfood_flags_sync_request_failed", error=str(e))
        return

    if response.status_code == 304:
        return

    if response.status_code != 200:
        logger.warning(
            "cross_region_dogfood_flags_sync_bad_status",
            status_code=response.status_code,
        )
        return

    try:
        payload = response.json()
    except ValueError as e:
        capture_exception_throttled(_SYNC_FAILURE_CAPTURE_THROTTLE_KEY, e, _SYNC_FAILURE_CAPTURE_THROTTLE_TTL)
        logger.warning("cross_region_dogfood_flags_sync_bad_json")
        return

    if not isinstance(payload, dict):
        # A malformed-but-valid-JSON body (e.g. null, a list) would otherwise be cached
        # verbatim and served to every EU pod until the next successful sync.
        logger.warning("cross_region_dogfood_flags_sync_unexpected_shape", payload_type=type(payload).__name__)
        return

    # update_cache (not bare set_cache_value) for parity with the signal-driven write
    # path: it emits the cache-sync metrics dashboards watch, and its info log only
    # fires when flags actually changed, since unchanged upstreams 304 above. The
    # write is unconditional (no skip_if_unchanged): a 200 already means the content
    # changed, and a bare int key isn't tracked in the expiry sorted set (unlike a
    # Team key), so this write is what re-stamps the Redis TTL. On a long run of 304s
    # the entry can still expire; that self-heals within one tick, because the etag
    # expires with it, so the next poll sends no If-None-Match and gets a full 200.
    flag_definitions_hypercache.update_cache(DOGFOOD_SELF_TEAM_ID, data=payload)
