"""DRF serializers for release."""

from django.db import models

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.models import OrganizationMembership

from ..facade.contracts import (
    MAX_LINKED,
    MAX_METRICS,
    LinkedBroadcastDTO,
    LinkedInsightDTO,
    LinkedSendDTO,
    LinkedSurveyDTO,
    ReleaseDTO,
    ReleaseGoalDirection,
)


class BroadcastSearchQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=200, help_text="Part of the broadcast name to match."
    )


class CatalogOrder(models.TextChoices):
    NEWEST = "-created_at", "Newest first"
    OLDEST = "created_at", "Oldest first"


class CatalogUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="ID of the user.")
    uuid = serializers.UUIDField(help_text="UUID of the user.")
    first_name = serializers.CharField(help_text="First name of the user.")
    last_name = serializers.CharField(help_text="Last name of the user.")
    email = serializers.EmailField(help_text="Email address of the user.")


def _user_ids(value: str) -> list[int]:
    try:
        return [int(part) for part in value.split(",") if part.strip()]
    except ValueError:
        raise serializers.ValidationError("Pass user IDs separated by commas.")


class CatalogFlagsQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=200, help_text="Part of the flag key or name to match."
    )
    created_by = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="Comma-separated user IDs. Only flags created by one of them are listed.",
    )
    order = serializers.ChoiceField(
        required=False,
        default=CatalogOrder.NEWEST,
        choices=CatalogOrder.choices,
        help_text="Sort by creation time: -created_at for newest first, created_at for oldest first.",
    )

    def validate_created_by(self, value: str) -> list[int]:
        return _user_ids(value)

    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=100, help_text="How many flags to return, at most 100."
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0, help_text="How many flags to skip.")


class CatalogFlagSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="ID of the feature flag.")
    key = serializers.CharField(help_text="Key of the feature flag.")
    active = serializers.BooleanField(help_text="True when the flag is enabled.")
    created_at = serializers.DateTimeField(help_text="When the flag was created.")
    created_by = CatalogUserSerializer(allow_null=True, help_text="Who created the flag, if known.")


class CatalogFlagsResponseSerializer(serializers.Serializer):
    results = CatalogFlagSerializer(many=True, help_text="Flags the caller can see, in the requested order.")
    has_more = serializers.BooleanField(help_text="True when more flags follow this page.")


class CatalogReleasesQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=200, help_text="Part of the release name to match."
    )
    owner = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        help_text="Comma-separated user IDs. Only releases owned by one of them are listed.",
    )
    order = serializers.ChoiceField(
        required=False,
        default=CatalogOrder.NEWEST,
        choices=CatalogOrder.choices,
        help_text="Sort by creation time: -created_at for newest first, created_at for oldest first.",
    )
    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=100, help_text="How many releases to return, at most 100."
    )
    cursor = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=100, help_text="next_cursor of the previous page."
    )
    feature_flag_id = serializers.IntegerField(
        required=False, min_value=1, help_text="Only releases that link this feature flag."
    )

    def validate_owner(self, value: str) -> list[int]:
        return _user_ids(value)


class CatalogReleaseSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the release.")
    name = serializers.CharField(help_text="Name of the release.")
    created_at = serializers.DateTimeField(help_text="When the release was created.")
    owner = CatalogUserSerializer(allow_null=True, help_text="Who owns the release, if anyone.")


class CatalogReleasesResponseSerializer(serializers.Serializer):
    results = CatalogReleaseSerializer(many=True, help_text="Releases of the project, in the requested order.")
    next_cursor = serializers.CharField(
        allow_null=True, help_text="Pass as cursor to fetch the next page. Null when no more releases follow."
    )


class FlagReleasesQuerySerializer(serializers.Serializer):
    feature_flag_id = serializers.IntegerField(min_value=1, help_text="ID of the feature flag to find releases for.")


class ReleaseRefSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the release.")
    name = serializers.CharField(help_text="Name of the release.")


class ReleaseSuggestionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the release.")
    name = serializers.CharField(help_text="Name of the release.")
    matched_terms = serializers.ListField(
        child=serializers.CharField(),
        help_text="Words the flag shares with the release's name, description or linked flags.",
    )


class FlagReleasesSerializer(serializers.Serializer):
    feature_flag_id = serializers.IntegerField(help_text="ID of the feature flag.")
    auto_release = serializers.BooleanField(
        help_text="True when this project puts each new flag in a release of its own about a minute after it is created, unless the flag is already in a release."
    )
    current = ReleaseRefSerializer(many=True, help_text="Releases that already link this flag.")
    suggestions = ReleaseSuggestionSerializer(
        many=True,
        help_text="Up to 5 existing releases this flag probably belongs to, best match first. Empty when nothing matches.",
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


class MetricGoalSerializer(serializers.Serializer):
    insight_id = serializers.IntegerField(
        min_value=1, max_value=2**31 - 1, help_text="ID of the metric insight the goal is for."
    )
    direction = serializers.ChoiceField(
        choices=ReleaseGoalDirection.choices,
        help_text="at_least when the metric should reach the value, at_most when it should stay at or below it.",
    )
    value = serializers.FloatField(help_text="Target value of the metric.")


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

    metric_insight_ids = serializers.ListField(
        child=serializers.IntegerField(),
        read_only=True,
        help_text="IDs of the insights that are the release's metrics. The first is the primary metric.",
    )

    metric_goals = MetricGoalSerializer(
        many=True, read_only=True, help_text="Target for each metric that has one. Metrics without a goal are left out."
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
    metric_insight_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=2**31 - 1),
        required=False,
        max_length=MAX_METRICS,
        help_text=(
            f"IDs of the saved trends insights that are the release's metrics, at most {MAX_METRICS}. "
            "The first is the primary metric, the rest are secondary. Replaces the current list."
        ),
    )

    metric_goals = serializers.ListField(
        child=MetricGoalSerializer(),
        required=False,
        max_length=MAX_METRICS,
        help_text=(
            "Targets for the release's metrics, at most one per metric. Each insight_id must be one of the "
            "metric_insight_ids. Replaces the current goals."
        ),
    )

    def validate_metric_goals(self, value: list[dict]) -> list[dict]:
        ids = [goal["insight_id"] for goal in value]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError("Each metric can have one goal.")
        return value

    def validate_metric_insight_ids(self, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Each metric can be listed once.")
        return value

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
