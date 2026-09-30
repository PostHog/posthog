from __future__ import annotations

from typing import cast

from django.db import models

from rest_framework import serializers

from posthog.api.documentation import PropertyItemSerializer, extend_schema_field

from products.error_tracking.backend.facade import contracts
from products.error_tracking.backend.presentation.views.issues import ErrorTrackingIssueSeverityField

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


class ErrorTrackingIssueOrderBy(models.TextChoices):
    LAST_SEEN = "last_seen", "last_seen"
    FIRST_SEEN = "first_seen", "first_seen"
    OCCURRENCES = "occurrences", "occurrences"
    USERS = "users", "users"
    SESSIONS = "sessions", "sessions"


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
        choices=ErrorTrackingIssueOrderBy.choices,
        required=False,
        default="occurrences",
        help_text="Field used to sort issues. Defaults to occurrences.",
    )
    orderDirection = serializers.ChoiceField(
        choices=["ASC", "DESC"], required=False, default="DESC", help_text="Sort direction. Defaults to DESC."
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        default=10,
        help_text="Page size. Defaults to 10. Use nextOffset to fetch more rows instead of a large page.",
    )
    offset = serializers.IntegerField(required=False, min_value=0, default=0, help_text="Pagination offset.")
    volumeResolution = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=200,
        default=0,
        help_text="Number of volume buckets. Defaults to 0, which returns only aggregate counts without volume buckets.",
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
    includeBreakdown = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Set true to include the issue page breakdowns: the most common paths (or URLs when events have no path), "
            "screens, browsers, OS, libraries, library versions, and app versions, each with a count, plus the "
            "sessions with the most events. Covers at most the last 30 days of dateRange. Adds one aggregate query, "
            "so request it only to answer where, for whom, or on which platforms the issue happens. Defaults to false."
        ),
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
    include = serializers.ListField(
        child=serializers.ChoiceField(
            choices=[
                "exception",
                "stacktrace",
                "code_variables",
                "environment",
                "release",
                "navigation",
                "correlation",
                "diagnostics",
            ]
        ),
        required=False,
        help_text=(
            "Context groups to return. Defaults to exception, environment, navigation, and correlation. "
            "Request stacktrace for frames, code_variables for captured and SDK-masked frame variables, release for "
            "release metadata, or diagnostics for ingestion errors. code_variables implies stacktrace."
        ),
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
    name = serializers.CharField(required=False, allow_null=True, help_text="Issue name.")
    description = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Issue description. List rows truncate it to a short preview; the issue detail query returns it in full.",
    )
    status = serializers.CharField(required=False, help_text="Issue status.")
    severity = ErrorTrackingIssueSeverityField(
        choices=contracts.ERROR_TRACKING_ISSUE_SEVERITIES,
        required=False,
        allow_null=True,
        help_text="Issue severity, or null when no severity is assigned.",
    )
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


class ErrorTrackingBreakdownValueSerializer(serializers.Serializer):
    value = serializers.CharField(help_text="Property value.")
    count = serializers.IntegerField(help_text="Number of matching events with this value.")


def breakdown_values_field(help_text: str) -> serializers.ListField:
    return serializers.ListField(child=ErrorTrackingBreakdownValueSerializer(), required=False, help_text=help_text)


class ErrorTrackingBreakdownTopValuesSerializer(serializers.Serializer):
    path = breakdown_values_field("Most common $pathname values, most frequent first.")
    url = breakdown_values_field(
        "Most common $current_url values, most frequent first. Returned only when events have no $pathname, as with "
        "backend SDKs."
    )
    screen = breakdown_values_field("Most common $screen_name values, most frequent first.")
    browser = breakdown_values_field("Most common $browser values, most frequent first.")
    os = breakdown_values_field("Most common $os values, most frequent first.")
    library = breakdown_values_field("Most common $lib values, most frequent first.")
    library_version = breakdown_values_field("Most common $lib_version values, most frequent first.")
    app_version = breakdown_values_field("Most common $app_version values, most frequent first.")


class ErrorTrackingIssueBreakdownSerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(help_text="Start of the range that the breakdown covers.")
    date_to = serializers.DateTimeField(help_text="End of the range that the breakdown covers.")
    range_limited = serializers.BooleanField(
        help_text="True when the requested range was longer than 30 days and the breakdown covers only the last 30."
    )
    occurrences = serializers.IntegerField(help_text="Matching exception events in the breakdown range.")
    sample_session_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Up to 5 $session_id values with the most matching events, for session recording lookups.",
    )
    top_values = ErrorTrackingBreakdownTopValuesSerializer(
        help_text="Most common values for each dimension. A dimension with no values is left out."
    )


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
    breakdown = ErrorTrackingIssueBreakdownSerializer(
        required=False, help_text="Aggregate over matching events. Returned only when includeBreakdown is true."
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
