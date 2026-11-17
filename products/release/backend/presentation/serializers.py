"""DRF serializers for release."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.models import OrganizationMembership

from ..facade.contracts import (
    MAX_LINKED,
    LinkedBroadcastDTO,
    LinkedInsightDTO,
    LinkedSendDTO,
    LinkedSurveyDTO,
    ReleaseDTO,
)


class BroadcastSearchQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=200, help_text="Part of the broadcast name to match."
    )


class CatalogFlagsQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=200, help_text="Part of the flag key or name to match."
    )
    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=100, help_text="How many flags to return, at most 100."
    )
    offset = serializers.IntegerField(
        required=False, default=0, min_value=0, help_text="How many flags to skip, newest first."
    )


class CatalogFlagSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="ID of the feature flag.")
    key = serializers.CharField(help_text="Key of the feature flag.")
    active = serializers.BooleanField(help_text="True when the flag is enabled.")
    created_at = serializers.DateTimeField(help_text="When the flag was created.")


class CatalogFlagsResponseSerializer(serializers.Serializer):
    results = CatalogFlagSerializer(many=True, help_text="Flags the caller can see, newest first.")
    has_more = serializers.BooleanField(help_text="True when more flags follow this page.")


class CatalogReleasesQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=200, help_text="Part of the release name to match."
    )
    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=100, help_text="How many releases to return, at most 100."
    )
    cursor = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=100, help_text="next_cursor of the previous page."
    )


class CatalogReleaseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the release.")
    name = serializers.CharField(help_text="Name of the release.")
    created_at = serializers.DateTimeField(help_text="When the release was created.")


class CatalogReleasesResponseSerializer(serializers.Serializer):
    results = CatalogReleaseSerializer(many=True, help_text="Releases of the project, newest first.")
    next_cursor = serializers.CharField(
        allow_null=True, help_text="Pass as cursor to fetch the next page. Null when no more releases follow."
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


class LinkedInsightSerializer(DataclassSerializer):
    deleted = serializers.BooleanField(
        read_only=True, help_text="True when the insight was deleted after it was linked."
    )

    class Meta:
        dataclass = LinkedInsightDTO


class LinkedSurveySerializer(DataclassSerializer):
    class Meta:
        dataclass = LinkedSurveyDTO


class ReleaseSerializer(DataclassSerializer):
    surveys = LinkedSurveySerializer(
        many=True,
        read_only=True,
        help_text="ID, name, dates, targeting flag and archived state of each linked survey the caller can see.",
    )

    insights = LinkedInsightSerializer(
        many=True,
        read_only=True,
        help_text="ID, short ID, name and dates of each linked insight the caller can see, including deleted ones.",
    )

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
    survey_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        max_length=MAX_LINKED,
        help_text=f"IDs of the surveys that collect feedback on the release, at most {MAX_LINKED}.",
    )
    insight_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=2**31 - 1),
        required=False,
        max_length=MAX_LINKED,
        help_text=f"IDs of the saved insights that measure the release, at most {MAX_LINKED}.",
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


class MergeReleasesSerializer(serializers.Serializer):
    release_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        max_length=MAX_LINKED,
        help_text=(
            "IDs of the releases to merge into this one. Their flags, broadcasts, surveys and insights move to this "
            "release, then they are deleted."
        ),
    )
    name = serializers.CharField(
        max_length=255,
        required=False,
        help_text="New name for the merged release. Keeps the current name when left out.",
    )


class ImportAllResponseSerializer(serializers.Serializer):
    created_count = serializers.IntegerField(help_text="How many releases the import created.")
