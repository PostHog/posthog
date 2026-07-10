from __future__ import annotations

from typing import cast

from rest_framework import serializers

from posthog.api.documentation import PropertyItemSerializer, extend_schema_field

STRING_OR_STRING_LIST_SCHEMA = {
    "oneOf": [
        {"type": "string"},
        {"type": "array", "items": {"type": "string"}, "minItems": 1},
    ]
}

JSON_OBJECT_SCHEMA = {"type": "object", "additionalProperties": True}


@extend_schema_field(STRING_OR_STRING_LIST_SCHEMA)
class StringOrStringListField(serializers.Field):
    def to_internal_value(self, data: object) -> str | list[str]:
        if isinstance(data, str):
            return data
        if isinstance(data, list) and data and all(isinstance(item, str) for item in data):
            return cast(list[str], data)
        raise serializers.ValidationError("Expected a string or a non-empty list of strings.")

    def to_representation(self, value: object) -> str | list[str]:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return [str(item) for item in value]
        return str(value)


@extend_schema_field(
    {
        "oneOf": [{"type": "string"}, {"type": "integer"}],
    }
)
class StringOrIntegerField(serializers.Field):
    def to_internal_value(self, data: object) -> str | int:
        if isinstance(data, bool):
            raise serializers.ValidationError("Expected a string or integer.")
        if isinstance(data, int | str):
            return data
        raise serializers.ValidationError("Expected a string or integer.")

    def to_representation(self, value: object) -> str | int:
        return value if isinstance(value, int | str) else str(value)


@extend_schema_field(JSON_OBJECT_SCHEMA)
class JSONObjectField(serializers.JSONField):
    pass


class ErrorTrackingDateRangeSerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        help_text="Start of the date range as an ISO timestamp or relative date such as -7d. Defaults to -7d.",
    )
    date_to = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="End of the date range as an ISO timestamp or relative date. Defaults to now when omitted.",
    )


def validate_filter_group(value: list[dict[str, object]]) -> list[dict[str, object]]:
    for item in value:
        if item.get("type") == "hogql":
            raise serializers.ValidationError("HogQL property filters are not supported here.")
    return value


class ErrorTrackingAssigneeSerializer(serializers.Serializer):
    id = StringOrIntegerField(help_text="User ID or role UUID to filter by.")
    type = serializers.ChoiceField(choices=["user", "role"], help_text="Assignee target type: user or role.")


class ErrorTrackingIssuesListQueryRequestSerializer(serializers.Serializer):
    dateRange = ErrorTrackingDateRangeSerializer(
        required=False,
        help_text="Date range for issue aggregates. Defaults to the last 7 days.",
    )
    status = serializers.ChoiceField(
        choices=["archived", "active", "resolved", "pending_release", "suppressed", "all"],
        required=False,
        default="active",
        help_text="Filter by issue status. Defaults to active.",
    )
    assignee = ErrorTrackingAssigneeSerializer(
        required=False,
        allow_null=True,
        help_text="Filter by issue assignee. Omit to include all assignees.",
    )
    filterTestAccounts = serializers.BooleanField(
        required=False,
        default=True,
        help_text="When true, exclude internal/test account data from results. Defaults to true.",
    )
    searchQuery = serializers.CharField(
        required=False,
        max_length=500,
        help_text="Free-text search across exception types, values, stack frames, and email fields.",
    )
    filterGroup = serializers.ListField(
        child=PropertyItemSerializer(),
        required=False,
        default=list,
        help_text="Advanced flat AND property filters. Prefer typed shortcut fields when they fit. HogQL filters are rejected.",
    )
    orderBy = serializers.ChoiceField(
        choices=["last_seen", "first_seen", "occurrences", "users", "sessions"],
        required=False,
        default="occurrences",
        help_text="Field used to sort issues. Defaults to occurrences.",
    )
    orderDirection = serializers.ChoiceField(
        choices=["ASC", "DESC"], required=False, default="DESC", help_text="Sort direction. Defaults to DESC."
    )
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=25, help_text="Page size.")
    offset = serializers.IntegerField(required=False, min_value=0, default=0, help_text="Pagination offset.")
    volumeResolution = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=200,
        default=0,
        help_text="Number of volume buckets. Defaults to 0 for compact aggregate counts.",
    )
    library = StringOrStringListField(
        required=False, help_text="Filter by SDK/library value from event $lib, for example posthog-js."
    )
    release = serializers.CharField(
        required=False,
        max_length=500,
        help_text="Filter by exact release ID, version, or git commit ID captured in $exception_releases.",
    )
    fingerprint = StringOrStringListField(
        required=False, help_text="Filter by exact exception fingerprint hash, not fuzzy search."
    )
    user = serializers.CharField(required=False, max_length=500, help_text="Search user/email text.")
    personId = serializers.UUIDField(required=False, help_text="Filter by exact PostHog person UUID.")
    url = serializers.CharField(required=False, max_length=1000, help_text="Filter by current URL substring.")
    filePath = serializers.CharField(
        required=False, max_length=1000, help_text="Search stack-frame source/file path text."
    )

    def validate_filterGroup(self, value: list[dict[str, object]]) -> list[dict[str, object]]:
        return validate_filter_group(value)


class ErrorTrackingIssueQueryRequestSerializer(serializers.Serializer):
    issueId = serializers.UUIDField(help_text="Error tracking issue ID.")
    dateRange = ErrorTrackingDateRangeSerializer(
        required=False,
        help_text="Date range for issue impact and latest-event metadata. Defaults to the last 7 days.",
    )
    filterTestAccounts = serializers.BooleanField(
        required=False,
        default=True,
        help_text="When true, exclude internal/test account data from results. Defaults to true.",
    )
    volumeResolution = serializers.IntegerField(
        required=False, min_value=0, max_value=200, default=0, help_text="Volume buckets. Maximum 200."
    )
    includeSparkline = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Set true to include a compact numeric occurrence sparkline. Defaults to false.",
    )


class ErrorTrackingIssueEventsQueryRequestSerializer(serializers.Serializer):
    issueId = serializers.UUIDField(help_text="Error tracking issue ID.")
    dateRange = ErrorTrackingDateRangeSerializer(
        required=False,
        help_text="Date range for sampled exception events. Defaults to the last 7 days.",
    )
    filterTestAccounts = serializers.BooleanField(
        required=False,
        default=True,
        help_text="When true, exclude internal/test account data from results. Defaults to true.",
    )
    filterGroup = serializers.ListField(
        child=PropertyItemSerializer(),
        required=False,
        default=list,
        help_text="Advanced flat AND property filters applied to sampled events. HogQL filters are rejected.",
    )
    searchQuery = serializers.CharField(
        required=False,
        max_length=500,
        help_text="Search exception types, exception values, and current URL among sampled events.",
    )
    orderDirection = serializers.ChoiceField(
        choices=["ASC", "DESC"], required=False, default="DESC", help_text="Timestamp sort direction. Defaults to DESC."
    )
    limit = serializers.IntegerField(required=False, min_value=1, max_value=20, default=1, help_text="Page size.")
    offset = serializers.IntegerField(required=False, min_value=0, default=0, help_text="Pagination offset.")
    verbosity = serializers.ChoiceField(
        choices=["summary", "stack", "raw"],
        required=False,
        default="summary",
        help_text="Controls exception detail size: summary, stack, or raw. Defaults to summary.",
    )
    onlyAppFrames = serializers.BooleanField(
        required=False,
        default=True,
        help_text="When true, include only stack frames marked in_app. Defaults to true.",
    )

    def validate_filterGroup(self, value: list[dict[str, object]]) -> list[dict[str, object]]:
        return validate_filter_group(value)


class ErrorTrackingAssigneeResponseSerializer(serializers.Serializer):
    id = StringOrIntegerField(required=False, allow_null=True, help_text="Assignee user ID or role UUID.")
    type = serializers.CharField(required=False, allow_null=True, help_text="Assignee type.")


class ErrorTrackingVolumeBucketSerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Bucket timestamp label.")  # type: ignore[assignment]
    value = serializers.FloatField(required=False, allow_null=True, help_text="Occurrence count for the bucket.")


class ErrorTrackingImpactSerializer(serializers.Serializer):
    occurrences = serializers.FloatField(required=False, help_text="Exception occurrence count.")
    users = serializers.FloatField(required=False, help_text="Unique user count.")
    sessions = serializers.FloatField(required=False, help_text="Unique session count.")


class ErrorTrackingAggregationsSerializer(ErrorTrackingImpactSerializer):
    volumeRange = serializers.ListField(
        child=serializers.FloatField(), required=False, help_text="Occurrence counts per volume bucket."
    )
    volume_buckets = serializers.ListField(
        child=ErrorTrackingVolumeBucketSerializer(), required=False, help_text="Labeled volume buckets."
    )


class ErrorTrackingIssueListItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Error tracking issue ID.")
    fingerprint = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Deterministic current fingerprint used for issue links, selected by earliest creation time and ID.",
    )
    name = serializers.CharField(required=False, allow_null=True, help_text="Issue name.")
    description = serializers.CharField(required=False, allow_null=True, help_text="Issue description.")
    status = serializers.CharField(required=False, help_text="Issue status.")
    first_seen = serializers.DateTimeField(required=False, allow_null=True, help_text="First seen timestamp.")
    last_seen = serializers.DateTimeField(required=False, allow_null=True, help_text="Last seen timestamp.")
    library = serializers.CharField(required=False, allow_null=True, help_text="SDK/library associated with the issue.")
    source = serializers.CharField(  # type: ignore[assignment]
        required=False, allow_null=True, help_text="Top source/file associated with the issue."
    )
    assignee = ErrorTrackingAssigneeResponseSerializer(required=False, allow_null=True, help_text="Issue assignee.")
    aggregations = ErrorTrackingAggregationsSerializer(required=False, allow_null=True, help_text="Aggregate counts.")


class ErrorTrackingIssuesListResponseSerializer(serializers.Serializer):
    results = ErrorTrackingIssueListItemSerializer(many=True, help_text="Issue rows.")
    hasMore = serializers.BooleanField(help_text="Whether more results are available.")
    limit = serializers.IntegerField(help_text="Page size.")
    offset = serializers.IntegerField(help_text="Current offset.")
    nextOffset = serializers.IntegerField(
        required=False, help_text="Offset to fetch the next page when hasMore is true."
    )


class ErrorTrackingTopFrameSerializer(serializers.Serializer):
    function = serializers.CharField(required=False, help_text="Frame function name.")
    source = serializers.CharField(required=False, help_text="Frame source, filename, or module.")  # type: ignore[assignment]
    line = serializers.IntegerField(required=False, help_text="Line number.")
    column = serializers.IntegerField(required=False, help_text="Column number.")
    in_app = serializers.BooleanField(required=False, help_text="Whether the frame is an application frame.")


class ErrorTrackingLatestReleaseSerializer(serializers.Serializer):
    version = serializers.CharField(required=False, help_text="Release version.")
    project = serializers.CharField(required=False, help_text="Release project/library.")
    timestamp = serializers.CharField(required=False, help_text="Release timestamp.")
    commit_id = serializers.CharField(required=False, help_text="Git commit ID.")
    branch = serializers.CharField(required=False, help_text="Git branch.")
    repo_name = serializers.CharField(required=False, help_text="Git repository name.")


class ErrorTrackingIssueDetailSerializer(ErrorTrackingIssueListItemSerializer):
    function = serializers.CharField(
        required=False, allow_null=True, help_text="Top function associated with the issue."
    )
    top_in_app_frame = ErrorTrackingTopFrameSerializer(required=False, help_text="Top in_app application frame.")
    latest_release = ErrorTrackingLatestReleaseSerializer(required=False, help_text="Latest release metadata.")
    impact = ErrorTrackingImpactSerializer(required=False, help_text="Compact impact counts.")
    sparkline = serializers.ListField(
        child=serializers.FloatField(), required=False, help_text="Optional compact occurrence sparkline."
    )


class ErrorTrackingEventSerializer(serializers.Serializer):
    uuid = serializers.CharField(required=False, help_text="Event UUID.")
    distinct_id = serializers.CharField(required=False, help_text="Event distinct ID.")
    timestamp = serializers.DateTimeField(required=False, help_text="Event timestamp.")
    properties = JSONObjectField(required=False, help_text="Normalized sampled exception event properties.")


class ErrorTrackingIssueEventsResponseSerializer(serializers.Serializer):
    results = ErrorTrackingEventSerializer(many=True, help_text="Sampled exception events.")
    hasMore = serializers.BooleanField(help_text="Whether more results are available.")
    limit = serializers.IntegerField(help_text="Page size.")
    offset = serializers.IntegerField(help_text="Current offset.")
    nextOffset = serializers.IntegerField(
        required=False, help_text="Offset to fetch the next page when hasMore is true."
    )
