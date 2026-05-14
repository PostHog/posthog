from typing import Any, cast
from uuid import UUID

from django.db.models import QuerySet

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field, extend_schema_view
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.organization import Organization
from posthog.models.user import User

from products.referrals.backend.models import (
    REFEREE_STATE_ERRORS_KEY,
    SIGNED_UP_AT_KEY,
    SIGNED_UP_USER_ID_KEY,
    SocialReferral,
)


@extend_schema_field(OpenApiTypes.OBJECT)
class SocialReferralRefereeStateField(serializers.JSONField):
    """OpenAPI object shape for per-invited-org referral tracking state."""


def _referral_invite_signed_up_user_display_name_lookup(user_ids: list[int]) -> dict[int, str]:
    """Map user pk → display string (full name, else email). Omits ids with no row (deleted user)."""
    if not user_ids:
        return {}
    unique_ids = list(dict.fromkeys(user_ids))
    lookup: dict[int, str] = {}
    for user in User.objects.filter(pk__in=unique_ids).only("id", "first_name", "last_name", "email"):
        label = user.get_full_name().strip()
        if not label:
            label = (user.email or "").strip()
        if label:
            lookup[user.pk] = label
    return lookup


def _coerce_signed_up_user_id(raw: dict[str, Any]) -> int | None:
    uid_raw = raw.get(SIGNED_UP_USER_ID_KEY)
    if uid_raw is None:
        return None
    if isinstance(uid_raw, bool):
        return None
    if isinstance(uid_raw, int):
        return uid_raw
    if isinstance(uid_raw, str) and uid_raw.isdigit():
        return int(uid_raw)
    return None


class SocialReferralRefereeInviteSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(
        help_text="UUID of the organization that signed up via this referral link.",
    )
    organization_name = serializers.CharField(
        help_text="Current display name of the invited organization.",
    )
    first_event_sent = serializers.BooleanField(
        help_text="Whether this organization has sent its first ingested event.",
    )
    signed_up_at = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="ISO 8601 datetime when this organization was first attributed at signup, if recorded.",
    )
    signed_up_user_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Primary key of the user who signed up the invited organization; null if unknown or cleared.",
    )
    signed_up_user_display_name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Resolved full name or email of signed_up_user_id when that user still exists; null if missing.",
    )


class SocialReferralSerializer(serializers.ModelSerializer):
    organization = serializers.PrimaryKeyRelatedField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    referee_state = SocialReferralRefereeStateField(
        required=False,
        help_text="Map of invited organization UUID (string) to referral progress "
        f"(`first_event_sent`, `{SIGNED_UP_AT_KEY}`, `{SIGNED_UP_USER_ID_KEY}`, etc.).",
    )
    referee_invites = serializers.SerializerMethodField(
        read_only=True,
        help_text="Invited organizations from referee_state with organization and signup-user display names resolved.",
    )

    class Meta:
        model = SocialReferral
        fields = [
            "id",
            "organization",
            "user",
            "referee_state",
            "referee_invites",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "organization",
            "user",
            "created_at",
        ]

    def validate_referee_state(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise serializers.ValidationError("referee_state must be an object.")
        return value

    @extend_schema_field(SocialReferralRefereeInviteSerializer(many=True))
    def get_referee_invites(self, obj: SocialReferral) -> list[dict[str, Any]]:
        state_raw = obj.referee_state
        if not isinstance(state_raw, dict):
            return []

        entries: list[tuple[UUID, bool, str | None, int | None]] = []
        for key, raw in state_raw.items():
            if key == REFEREE_STATE_ERRORS_KEY:
                continue
            if not isinstance(raw, dict):
                continue
            try:
                org_id = UUID(key)
            except ValueError:
                continue
            first_event_sent = raw.get("first_event_sent") is True
            signed_raw = raw.get(SIGNED_UP_AT_KEY)
            signed_up_at: str | None = signed_raw if isinstance(signed_raw, str) and signed_raw else None
            signed_up_user_id = _coerce_signed_up_user_id(raw)
            entries.append((org_id, first_event_sent, signed_up_at, signed_up_user_id))

        if not entries:
            return []

        org_ids = [pair[0] for pair in entries]
        name_lookup: dict[UUID, str] = {
            row[0]: row[1] for row in Organization.objects.filter(pk__in=org_ids).values_list("id", "name")
        }

        signed_user_ids = [uid for *_, uid in entries if uid is not None]
        user_display_lookup = _referral_invite_signed_up_user_display_name_lookup(signed_user_ids)

        unknown_label = "Unknown organization"
        return [
            {
                "organization_id": org_id,
                "organization_name": name_lookup.get(org_id, unknown_label),
                "first_event_sent": sent,
                "signed_up_at": signed_up,
                "signed_up_user_id": signed_up_uid,
                "signed_up_user_display_name": (
                    user_display_lookup.get(signed_up_uid) if signed_up_uid is not None else None
                ),
            }
            for org_id, sent, signed_up, signed_up_uid in entries
        ]


# TODO(permissioning): Decide creator-only vs org-wide visibility; personal API keys / OAuth scopes;
# internal/system updates to `referee_state` without an end-user principal.
@extend_schema_view(
    list=extend_schema(summary="List social referrals"),
    create=extend_schema(summary="Create social referral"),
    retrieve=extend_schema(summary="Retrieve social referral"),
    update=extend_schema(summary="Update social referral"),
    partial_update=extend_schema(summary="Partially update social referral"),
    destroy=extend_schema(summary="Delete social referral"),
)
@extend_schema(tags=["core"])
class SocialReferralViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for referral share links under an organization."""

    scope_object = "organization"
    queryset = SocialReferral.objects.all()
    serializer_class = SocialReferralSerializer
    # TODO(permissioning): Add explicit permission classes beyond TeamAndOrgViewSetMixin defaults; align with API scopes / AccessControl.
    permission_classes = []

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        user = cast(User, self.request.user)
        return queryset.filter(organization_id=self.organization_id, user_id=user.id)

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(organization_id=self.organization_id, user=self.request.user)
