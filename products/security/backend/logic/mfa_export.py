"""Reads the legacy Redis MFA bypasses for the hub's one-time import. Deleted at cut-over."""

from datetime import UTC, datetime, timedelta

from posthog.dataclasses import frozen
from posthog.helpers.two_factor_session import (
    CODE_BASED_VERIFICATION_BYPASS_REDIS_KEY,
    get_code_based_verification_global_disable,
)
from posthog.redis import get_client


@frozen
class GlobalBypass:
    reason: str
    actor: str | None
    expires_at: datetime


@frozen
class MfaExport:
    emails: tuple[str, ...]
    global_bypass: GlobalBypass | None


def export_mfa_bypasses() -> MfaExport:
    members = get_client().smembers(CODE_BASED_VERIFICATION_BYPASS_REDIS_KEY)
    emails = tuple(sorted(m.decode() if isinstance(m, bytes) else str(m) for m in members))
    state = get_code_based_verification_global_disable()
    global_bypass = None
    if state and state.get("expires_in_seconds"):
        global_bypass = GlobalBypass(
            reason=str(state.get("reason", "")),
            actor=state.get("disabled_by"),
            expires_at=datetime.now(UTC) + timedelta(seconds=int(state["expires_in_seconds"])),
        )
    return MfaExport(emails=emails, global_bypass=global_bypass)
