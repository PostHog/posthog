from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.models.utils import UUIDModel

USER_DISTINCT_ID_MAX_LEN = 200  # Must match `User.distinct_id` max_length

# Per-invited-org entry in `referee_state` (keyed by organization UUID string).
SIGNED_UP_AT_KEY = "signed_up_at"
# User who completed signup for the invited org; nullable if cleared after user deletion.
SIGNED_UP_USER_ID_KEY = "signed_up_user_id"

# Optional Shopify promo payloads on a referee entry (historical rows may still carry these keys).
REFEREE_ENTRY_SHOPIFY_DISCOUNT_CODES_KEY = "shopify_discount_codes"
REFEREE_ENTRY_SHOPIFY_CODE_RECORD_CODE = "code"
REFEREE_ENTRY_SHOPIFY_CODE_RECORD_ISSUED_AT = "issued_at"
REFEREE_ENTRY_SHOPIFY_CODE_RECORD_PRICE_RULE_ID = "price_rule_id"
REFEREE_ENTRY_SHOPIFY_CODE_RECORD_DISCOUNT_ID = "shopify_discount_id"
REFEREE_ENTRY_SHOPIFY_PROMO_LAST_ERROR_KEY = "shopify_promo_last_error"


def new_referee_entry_at_signup(*, signed_up_at_iso: str, signed_up_user_id: int) -> dict[str, Any]:
    """Build a referee_state value when an org is first attributed from a referral signup."""
    return {
        "first_event_sent": False,
        SIGNED_UP_AT_KEY: signed_up_at_iso,
        SIGNED_UP_USER_ID_KEY: signed_up_user_id,
    }


# Top-level `referee_state["errors"]` — not an invited org. Nested keys may include `ingestion_sync`
# (written when the Temporal ingestion activity fails for this row).
REFEREE_STATE_ERRORS_KEY = "errors"
REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY = "ingestion_sync"


class SocialReferral(UUIDModel):
    """
    Referral share link: who created it (org + user) plus JSON keyed by invited organization id (uuid string)
    tracking whether their first captured event landed.
    """

    referee_state = models.JSONField(
        default=dict,
        blank=True,
        help_text='Per-invited-org map: `{ "<organization_uuid>": { "first_event_sent": boolean, '
        '"signed_up_at": "<ISO-8601>", "signed_up_user_id": <int or null>, '
        '"shopify_discount_codes": [ { "code", "issued_at", "price_rule_id", "shopify_discount_id" }, ... ], ... } }`. '
        "Reserved top-level key: `errors` (ingestion sync failures).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="social_referrals",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        help_text="User who generated this referral link.",
    )

    class Meta:
        indexes = [
            models.Index(fields=["organization", "-created_at"], name="social_ref_org_created_idx"),
        ]


def record_signup_social_referral_attribution(
    *,
    referral_distinct_id: str,
    referee_organization: Organization,
    new_user: User,
) -> None:
    """Update or create referrer `SocialReferral` rows keyed by the new organization's id.

    `referral_distinct_id` is the referring user's analytics distinct id (`User.distinct_id`).
    Failures never propagate — callers assume signup continues regardless."""
    trimmed = referral_distinct_id.strip()
    if not trimmed:
        return
    key = trimmed[:USER_DISTINCT_ID_MAX_LEN]

    try:
        referrer = User.objects.only("pk", "current_organization_id", "distinct_id").filter(distinct_id=key).first()
        if referrer is None:
            capture_exception(
                ValueError("Social referral signup: referring distinct_id matched no user"),
                additional_properties={
                    "social_referral_context": "unknown_referring_distinct_id",
                    "social_referral_referring_distinct_id_prefix": key[:64],
                    "referee_organization_id": str(referee_organization.id),
                    "new_user_id": new_user.pk,
                },
            )
            return
        if referrer.pk == new_user.pk:
            return

        referrer_org_id = referrer.current_organization_id
        if referrer_org_id is None:
            return

        org_uuid_str = str(referee_organization.id)
        signed_up_at_iso = timezone.now().isoformat()

        with transaction.atomic():
            row = (
                SocialReferral.objects.select_for_update()
                .filter(organization_id=referrer_org_id, user_id=referrer.pk)
                .order_by("-created_at")
                .first()
            )

            if row is None:
                SocialReferral.objects.create(
                    organization_id=referrer_org_id,
                    user_id=referrer.pk,
                    referee_state={
                        org_uuid_str: new_referee_entry_at_signup(
                            signed_up_at_iso=signed_up_at_iso,
                            signed_up_user_id=new_user.pk,
                        ),
                    },
                )
                return

            merged: dict[str, object] = dict(row.referee_state) if isinstance(row.referee_state, dict) else {}
            if org_uuid_str not in merged:
                merged[org_uuid_str] = new_referee_entry_at_signup(
                    signed_up_at_iso=signed_up_at_iso,
                    signed_up_user_id=new_user.pk,
                )
                row.referee_state = merged
                row.save(update_fields=["referee_state"])
    except Exception as e:
        capture_exception(
            e,
            additional_properties={
                "social_referral_context": "signup_attribution_failed",
                "referee_organization_id": str(referee_organization.id),
                "new_user_id": new_user.pk,
            },
        )
