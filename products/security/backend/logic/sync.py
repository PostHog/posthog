"""Pulls this region's access rules from the security hub into the snapshot store."""

import time
from datetime import UTC, datetime
from typing import Literal

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


class InvalidSnapshot(Exception):
    pass


@frozen
class SyncResult:
    status: Literal["updated", "unchanged", "not_configured"]
    rule_count: int | None = None


def _mark_success() -> None:
    mark_synced(datetime.now(UTC))
    LAST_SYNC_GAUGE.set(time.time())


def sync_access_rules() -> SyncResult:
    if not settings.SECURITY_HUB_URL or not settings.SECURITY_HUB_REGION or not RULES_PURPOSE.enabled():
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
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("version"), str)
            or not isinstance(body.get("rules"), list)
            or body.get("region") != settings.SECURITY_HUB_REGION
        ):
            raise InvalidSnapshot("The hub answered with a snapshot this region can't use.")
    except Exception:
        SYNC_COUNTER.labels(result="failed").inc()
        raise

    count = write_snapshot(body["version"], body["rules"])
    _mark_success()
    SYNC_COUNTER.labels(result="updated").inc()
    logger.info("security_access_rules_synced", version=body["version"], rule_count=count)
    return SyncResult(status="updated", rule_count=count)
