"""What the hub-facing routes are allowed to reach. Keeps presentation out of logic/."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..logic.accounts import (
    CappedCount,
    CountableType as CountableType,
    Resolution,
    count_active_accounts,
    count_active_org_members,
    has_posthog_account,
    resolve_subject,
)
from ..logic.hub_auth import (
    INTERNAL_PURPOSE as INTERNAL_PURPOSE,
    claims_allow,
)
from ..logic.mfa_export import MfaExport, export_mfa_bypasses
from ..metrics import HUB_API_AUTH_COUNTER


def resolve(query: str) -> Resolution:
    return resolve_subject(query)


def count_accounts(target_type: CountableType, target_value: str) -> CappedCount:
    return count_active_accounts(target_type, target_value)


def count_org_members(organization_id: str) -> tuple[bool, CappedCount]:
    return count_active_org_members(organization_id)


def posthog_account_exists(*, user_uuid: str | None = None, organization_id: str | None = None) -> bool:
    return has_posthog_account(user_uuid=user_uuid, organization_id=organization_id)


def mfa_bypasses() -> MfaExport:
    return export_mfa_bypasses()


def token_allows(claims: Mapping[str, Any] | None, op: str) -> bool:
    return claims_allow(claims, op)


def record_call(op: str) -> None:
    HUB_API_AUTH_COUNTER.labels(op=op).inc()
