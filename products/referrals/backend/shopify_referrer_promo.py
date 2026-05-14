"""Create Shopify discount codes for social-referral referrers (Admin REST API)."""

from __future__ import annotations

import secrets
from typing import Any, NamedTuple

from django.conf import settings

import requests
import structlog

_LOGGER = structlog.get_logger(__name__)

# Shopify Admin REST — hardcoded for PostHog referral promos (not tenant/instance config).
_REFERRALS_SHOPIFY_SHOP_ADMIN_HOST = "posthog.myshopify.com"
REFERRALS_SHOPIFY_PRICE_RULE_ID = "1257938944161"
_REFERRALS_SHOPIFY_ADMIN_API_VERSION = "2026-04"

_SHOPIFY_REQUEST_TIMEOUT_S = 30
_MAX_CODE_ATTEMPTS = 5


class ReferrerDiscountCodeResult(NamedTuple):
    """Outcome of ``create_referrer_discount_code`` — Shopify REST discount_code resource."""

    code: str | None
    shopify_discount_id: str | None
    error_detail: str | None


def social_referral_shopify_promo_configured() -> bool:
    token = (getattr(settings, "SOCIAL_REFERRAL_SHOPIFY_ACCESS_TOKEN", "") or "").strip()
    return bool(token)


def _random_discount_code() -> str:
    return f"REF-{secrets.token_hex(5).upper()}"


def create_referrer_discount_code() -> ReferrerDiscountCodeResult:
    """POST a unique discount code under the configured price rule.

    Returns ``ReferrerDiscountCodeResult(code, shopify_discount_id, None)`` on success,
    ``ReferrerDiscountCodeResult(None, None, None)`` if Shopify isn't configured,
    or ``ReferrerDiscountCodeResult(None, None, error_detail)`` on failure.
    """
    if not social_referral_shopify_promo_configured():
        return ReferrerDiscountCodeResult(None, None, None)

    token = settings.SOCIAL_REFERRAL_SHOPIFY_ACCESS_TOKEN
    url = (
        f"https://{_REFERRALS_SHOPIFY_SHOP_ADMIN_HOST}/admin/api/"
        f"{_REFERRALS_SHOPIFY_ADMIN_API_VERSION}/price_rules/{REFERRALS_SHOPIFY_PRICE_RULE_ID}/discount_codes.json"
    )
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token,
    }

    last_error = "unknown error"
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = _random_discount_code()
        payload: dict[str, Any] = {"discount_code": {"code": code}}
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=_SHOPIFY_REQUEST_TIMEOUT_S)
        except requests.RequestException as exc:
            _LOGGER.warning("social_referral_shopify_discount_request_failed", error=str(exc))
            return ReferrerDiscountCodeResult(None, None, str(exc))

        if response.ok:
            try:
                body = response.json()
            except ValueError:
                _LOGGER.warning("social_referral_shopify_discount_invalid_json", status=response.status_code)
                return ReferrerDiscountCodeResult(None, None, f"invalid JSON ({response.status_code})")
            discount = body.get("discount_code")
            if isinstance(discount, dict) and discount.get("code"):
                created = str(discount["code"])
                raw_id = discount.get("id")
                discount_id = str(raw_id) if raw_id is not None else None
                _LOGGER.info(
                    "social_referral_shopify_discount_created",
                    shopify_code_prefix=created[:8],
                    shopify_discount_id=discount_id,
                )
                return ReferrerDiscountCodeResult(created, discount_id, None)
            return ReferrerDiscountCodeResult(None, None, "missing discount_code in response")

        err_text = response.text[:2000] if response.text else ""
        last_error = f"HTTP {response.status_code}: {err_text}"
        if response.status_code == 422 and "already" in err_text.lower():
            _LOGGER.info("social_referral_shopify_discount_collision_retry")
            continue
        _LOGGER.warning(
            "social_referral_shopify_discount_rejected",
            status_code=response.status_code,
            body_prefix=err_text[:500],
        )
        return ReferrerDiscountCodeResult(None, None, last_error)

    return ReferrerDiscountCodeResult(None, None, last_error)
