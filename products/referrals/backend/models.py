from django.conf import settings
from django.db import models, transaction

from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.models.utils import UUIDModel

USER_DISTINCT_ID_MAX_LEN = 200  # Must match `User.distinct_id` max_length
DEFAULT_REFEREE_STATE_ENTRY = {"first_event_sent": False}


class SocialReferral(UUIDModel):
    """
    Referral share link: who created it (org + user) plus JSON keyed by invited organization id (uuid string)
    tracking whether their first captured event landed.
    """

    referee_state = models.JSONField(
        default=dict,
        blank=True,
        help_text='Per-invited-org map: `{ "<organization_uuid>": { "first_event_sent": boolean } }`.',
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
                    referee_state={org_uuid_str: dict(DEFAULT_REFEREE_STATE_ENTRY)},
                )
                return

            merged: dict[str, object] = dict(row.referee_state) if isinstance(row.referee_state, dict) else {}
            if org_uuid_str not in merged:
                merged[org_uuid_str] = dict(DEFAULT_REFEREE_STATE_ENTRY)
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
