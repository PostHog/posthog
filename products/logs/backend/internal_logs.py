"""Signs internal log batches the same way as nodejs/src/logs/internal-logs.ts, which also verifies them."""

import re
import hmac
import math
import hashlib
from datetime import UTC, datetime

INTERNAL_LOGS_HTTP_HEADER = "x-posthog-internal"

SIGNATURE_VERSION = "v1"

# No dot, because a dot divides the parts of the header value.
SOURCE_PATTERN = re.compile(r"^[a-z0-9_]{1,64}\Z")

# Keys must match the Node `INTERNAL_SOURCE_POLICIES`, because the logs consumer bills an unknown source.
INTERNAL_SOURCE_SERVICE_NAMES: dict[str, str] = {
    "hog_flow": "posthog-internal-workflows",
    "hog_function": "posthog-internal-hog-functions",
    "external_data_jobs": "posthog-internal-data-imports",
    "data_modeling_run": "posthog-internal-data-modeling",
    "batch_exports": "posthog-internal-batch-exports",
    "batch_exports_backfill": "posthog-internal-batch-exports",
    "dwh_cdp_producer_job": "posthog-internal-warehouse-cdp",
    "endpoints": "posthog-internal-endpoints",
    "alert_destination": "posthog-internal-alerts",
}


def parse_keys(comma_separated_keys: str) -> list[str]:
    return [key.strip() for key in comma_separated_keys.split(",") if key.strip()]


def compute_signature(key: str, source: str, team_id: int, signed_at: str) -> str:
    mac = hmac.new(
        key.encode(), f"{SIGNATURE_VERSION}|{source}|{team_id}|{signed_at}".encode(), hashlib.sha256
    ).hexdigest()
    return f"{SIGNATURE_VERSION}.{source}.{signed_at}.{mac}"


def sign_internal_logs(comma_separated_keys: str, source: str, team_id: int, signed_at: datetime | None = None) -> str:
    """Sign once per HTTP attempt, because a retried signature can fall outside the window and be billed."""
    keys = parse_keys(comma_separated_keys)
    if not keys:
        raise ValueError("Cannot sign posthog-internal batch: no signing key configured")
    if not SOURCE_PATTERN.match(source):
        raise ValueError(f"Cannot sign posthog-internal batch: invalid source {source!r}")
    epoch_seconds = math.floor((signed_at or datetime.now(UTC)).timestamp())
    return compute_signature(keys[0], source, team_id, str(epoch_seconds))
