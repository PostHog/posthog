"""Tokens between this region and the security hub, one secret per direction."""

import time
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, TypeGuard

from django.conf import settings

from posthog.jwt import PosthogJwtAudience
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

# The hub refuses a token that lives longer than this.
MAX_TOKEN_LIFETIME_SECONDS = 60
# encode_jwt sets exp from a clock read after mint_rules_token reads iat, so the hub measures
# exp - iat as the TTL plus whatever pause fell between the two reads.
MIN_MINT_MARGIN_SECONDS = 30
_MINT_TTL = timedelta(seconds=MAX_TOKEN_LIFETIME_SECONDS - MIN_MINT_MARGIN_SECONDS)

RULES_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.SECURITY_HUB_RULES,
    settings_name="SECURITY_HUB_OUTBOUND_JWT_SECRETS",
    default_ttl=_MINT_TTL,
)

INTERNAL_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.SECURITY_HUB_INTERNAL,
    settings_name="SECURITY_HUB_INBOUND_JWT_SECRETS",
    default_ttl=_MINT_TTL,
)


def mint_rules_token() -> str:
    return RULES_PURPOSE.mint({"region": settings.SECURITY_HUB_REGION, "op": "rules:read", "iat": int(time.time())})


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def claims_allow(claims: Mapping[str, Any] | None, op: str) -> bool:
    """Signature, expiry and audience are already verified. This pins the region, the
    operation and a short lifetime, so one leaked token opens one operation briefly."""
    if not claims:
        return False
    iat, exp = claims.get("iat"), claims.get("exp")
    return (
        claims.get("region") == settings.SECURITY_HUB_REGION
        and claims.get("op") == op
        and _is_int(iat)
        and _is_int(exp)
        and exp - iat <= MAX_TOKEN_LIFETIME_SECONDS
    )
