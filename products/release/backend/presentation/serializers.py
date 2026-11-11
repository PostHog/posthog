"""DRF serializers for release."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.models import OrganizationMembership

from ..facade.contracts import LinkedBroadcastDTO, LinkedSendDTO, ReleaseDTO

MAX_LINKED = 100


class BroadcastSearchQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=200, help_text="Part of the broadcast name to match."
    )


class BroadcastOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the broadcast.")
    name = serializers.CharField(help_text="Name of the broadcast.")
    status = serializers.CharField(help_text="Status of the broadcast, such as draft or active.")


class LinkedSendSerializer(DataclassSerializer):
    class Meta:
        dataclass = LinkedSendDTO


class LinkedBroadcastSerializer(DataclassSerializer):
    recent_sends = LinkedSendSerializer(
        many=True, read_only=True, help_text="The broadcast's most recent sends, newest first, at most 20."
    )

    class Meta:
        dataclass = LinkedBroadcastDTO


class ReleaseSerializer(DataclassSerializer):
    broadcasts = LinkedBroadcastSerializer(
        many=True,
        read_only=True,
        help_text="ID, name and status of each linked broadcast the caller can see. Deleted broadcasts are left out.",
    )

    has_hidden_flags = serializers.BooleanField(
        read_only=True,
        help_text="True when the release links flags the caller cannot see. Their IDs are left out of feature_flag_ids.",
    )

    class Meta:
        dataclass = ReleaseDTO


class WriteReleaseSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Name of the release.")
    description = serializers.CharField(
        allow_blank=True, required=False, help_text="What changes for the people who get the release."
    )
    owner_id = serializers.IntegerField(
        allow_null=True,
        required=False,
        help_text="ID of the user who owns the release. Must be a member of the project's organization.",
    )
    feature_flag_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=2**31 - 1),
        required=False,
        max_length=MAX_LINKED,
        help_text=f"IDs of the feature flags that control who gets the release, at most {MAX_LINKED}.",
    )
    broadcast_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        max_length=MAX_LINKED,
        help_text=f"IDs of the broadcasts that announce the release, at most {MAX_LINKED}.",
    )

    def validate_owner_id(self, value: int | None) -> int | None:
        if value is None:
            return value
        team = self.context["team"]
        if not OrganizationMembership.objects.filter(organization_id=team.organization_id, user_id=value).exists():
            raise serializers.ValidationError("The owner must be a member of this organization.")
        return value


class UpdateReleaseSerializer(WriteReleaseSerializer):
    name = serializers.CharField(max_length=255, required=False, help_text="Name of the release.")


class ImportAllResponseSerializer(serializers.Serializer):
    created_count = serializers.IntegerField(help_text="How many releases the import created.")
