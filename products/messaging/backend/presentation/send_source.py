"""Where a transactional email send came from: a direct API call or an SDK, and whether a migration rewrote the
call site. Attribution is best-effort and never changes how a send behaves."""

import re
from collections.abc import Mapping
from typing import Literal

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.utils import safe_cache_add, safe_cache_delete

logger = structlog.get_logger(__name__)

MIGRATED_FROM_HEADER = "X-PostHog-Migrated-From"
MIGRATION_SOURCES = frozenset({"resend"})
SDK_USER_AGENT = re.compile(r"posthog-(?:node|edge)/(?P<version>\d[\w.+-]{0,31})(?=\s|$)")


@frozen
class SendSource:
    source: Literal["api", "sdk"]
    sdk_version: str | None
    migrated_from: str | None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> "SendSource":
        sdk = SDK_USER_AGENT.match((headers.get("User-Agent") or "").strip())
        migrated_from = (headers.get(MIGRATED_FROM_HEADER) or "").strip().lower()
        return cls(
            source="sdk" if sdk else "api",
            sdk_version=sdk["version"] if sdk else None,
            migrated_from=migrated_from if migrated_from in MIGRATION_SOURCES else None,
        )

    def as_event_properties(self) -> dict[str, str | None]:
        return {"source": self.source, "sdk_version": self.sdk_version, "migrated_from": self.migrated_from}


def mark_organization_migrated(organization_id: str, send_source: SendSource) -> None:
    """Set the organization's `email_migrated_from` on its first migrated send. The cache mark keeps later sends
    from sending the group property again, so a newer migration never overwrites the first."""
    if not send_source.migrated_from:
        return
    mark_key = f"messaging:email_migrated_from:{organization_id}"
    if not safe_cache_add(mark_key, send_source.migrated_from):
        return
    if not _report_organization_migrated(organization_id, send_source.migrated_from):
        safe_cache_delete(mark_key)


def _report_organization_migrated(organization_id: str, migrated_from: str) -> bool:
    # The client returns no event id when it drops the event, for example when its queue is full.
    try:
        event_id = posthoganalytics.group_identify(
            "organization", organization_id, properties={"email_migrated_from": migrated_from}
        )
    except Exception:
        logger.warning("email_migrated_from_report_failed", organization_id=organization_id, exc_info=True)
        return False
    return event_id is not None
