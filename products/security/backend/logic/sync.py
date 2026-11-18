"""Pulls this region's access rules from the security hub into the snapshot store."""

import time
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

from django.conf import settings

import requests
import structlog

from posthog.dataclasses import frozen

from ..metrics import LAST_SYNC_GAUGE, SYNC_COUNTER
from .hub_auth import RULES_PURPOSE, mint_rules_token
from .snapshot import mark_synced, stored_version, write_snapshot

logger = structlog.get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 10
SNAPSHOT_PATH = "/webhooks/access-rules/snapshot"
_LOCAL_HOSTS = {"localhost", "127.0.0.1"}


class InvalidSnapshot(Exception):
    pass


@frozen
class SyncResult:
    status: Literal["updated", "unchanged", "not_configured", "stale"]
    rule_count: int | None = None


def _mark_success() -> None:
    mark_synced(datetime.now(UTC))
    LAST_SYNC_GAUGE.set(time.time())


def _hub_url_is_https_or_local(url: str) -> bool:
    """Refuses cleartext bearer tokens. http:// is allowed only for a local hub in DEBUG or TEST."""
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS and (settings.DEBUG or settings.TEST)


def _parse_generated_at_ms(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # A naive value has no fixed instant: .timestamp() would read it in the process's
    # local timezone rather than the hub's, silently misordering writes.
    if parsed.utcoffset() is None:
        return None
    return int(parsed.timestamp() * 1000)


def sync_access_rules() -> SyncResult:
    if not settings.SECURITY_HUB_URL or not settings.SECURITY_HUB_REGION or not RULES_PURPOSE.enabled():
        SYNC_COUNTER.labels(result="not_configured").inc()
        return SyncResult(status="not_configured")

    if not _hub_url_is_https_or_local(settings.SECURITY_HUB_URL):
        logger.warning("security_hub_url_refused_insecure_scheme")
        SYNC_COUNTER.labels(result="not_configured").inc()
        return SyncResult(status="not_configured")

    headers = {"Authorization": f"Bearer {mint_rules_token()}"}
    version = stored_version()
    if version:
        headers["If-None-Match"] = f'"{version}"'

    try:
        response = requests.get(
            f"{settings.SECURITY_HUB_URL.rstrip('/')}{SNAPSHOT_PATH}",
            params={"region": settings.SECURITY_HUB_REGION},
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 304:
            _mark_success()
            SYNC_COUNTER.labels(result="unchanged").inc()
            return SyncResult(status="unchanged")
        response.raise_for_status()
        body = response.json()
        generated_at_ms = _parse_generated_at_ms(body.get("generatedAt")) if isinstance(body, dict) else None
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("version"), str)
            or not isinstance(body.get("rules"), list)
            or body.get("region") != settings.SECURITY_HUB_REGION
            or generated_at_ms is None
        ):
            raise InvalidSnapshot("The hub answered with a snapshot this region can't use.")
    except Exception:
        SYNC_COUNTER.labels(result="failed").inc()
        raise

    outcome = write_snapshot(body["version"], body["rules"], generated_at_ms)
    # The hub answered, so this counts as contact even if the write lost the ordering race.
    _mark_success()
    if not outcome.applied:
        SYNC_COUNTER.labels(result="stale").inc()
        return SyncResult(status="stale", rule_count=outcome.rule_count)
    SYNC_COUNTER.labels(result="updated").inc()
    logger.info("security_access_rules_synced", version=body["version"], rule_count=outcome.rule_count)
    return SyncResult(status="updated", rule_count=outcome.rule_count)
