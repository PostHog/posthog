"""OpenAPI schema serializers for the Endpoints product.

These serializers document request/response shapes for drf-spectacular.
They do NOT replace the existing Pydantic validation or manual _serialize() logic —
they exist so the OpenAPI spec (and downstream MCP tools / generated TypeScript) gets
accurate type information and descriptions.
"""

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer


class EndpointRequestSerializer(serializers.Serializer):
    """Schema for creating/updating endpoints. OpenAPI docs only — validation uses Pydantic."""

    name = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Unique URL-safe name. Must start with a letter, only letters/numbers/hyphens/underscores, max 128 chars.",
    )
    query = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="HogQL or insight query this endpoint executes. Changing this auto-creates a new version.",
    )
    description = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Human-readable description of what this endpoint returns.",
    )
    data_freshness_seconds = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text=(
            "How fresh the data should be, in seconds. Must be one of: "
            "900 (15 min), 1800 (30 min), 3600 (1 h), 21600 (6 h), 43200 (12 h), "
            "86400 (24 h, default), 604800 (7 d). Controls cache TTL and materialization sync frequency."
        ),
    )
    is_active = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether this endpoint is available for execution via the API.",
    )
    is_materialized = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether query results are materialized to S3.",
    )
    derived_from_insight = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Short ID of the insight this endpoint was derived from.",
    )
    version = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Target a specific version for updates (defaults to current version).",
    )
    bucket_overrides = serializers.DictField(
        required=False,
        allow_null=True,
        help_text="Per-column bucket overrides for range variable materialization. Keys are column names, values are bucket keys.",
    )
    deleted = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Set to true to soft-delete this endpoint.",
    )


class EndpointMaterializationSerializer(serializers.Serializer):
    """Materialization status for an endpoint version."""

    name = serializers.CharField(
        help_text="URL-safe endpoint name.",
    )
    status = serializers.CharField(
        required=False,
        help_text="Current materialization status (e.g. 'Completed', 'Running').",
    )
    can_materialize = serializers.BooleanField(
        help_text="Whether this endpoint query can be materialized.",
    )
    reason = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Reason why materialization is not possible (only when can_materialize is false).",
    )
    last_materialized_at = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="ISO 8601 timestamp of the last successful materialization.",
    )
    error = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Last materialization error message, if any.",
    )
    saved_query_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of the underlying saved query backing this materialization. Only populated when the version is materialized.",
    )


class EndpointColumnSerializer(serializers.Serializer):
    """A column in the endpoint's query result."""

    name = serializers.CharField(help_text="Column name from the query SELECT clause.")
    type = serializers.CharField(
        help_text="Serialized column type: integer, float, string, datetime, date, boolean, array, json, or unknown.",
    )


class EndpointResponseSerializer(serializers.Serializer):
    """Full endpoint representation returned by list/retrieve/create/update."""

    id = serializers.UUIDField(help_text="Unique endpoint identifier (UUID).")
    name = serializers.CharField(help_text="URL-safe endpoint name, unique per team.")
    description = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="Human-readable description of the endpoint.",
    )
    query = serializers.JSONField(
        help_text="The HogQL or insight query definition (JSON object with 'kind' key).",
    )
    is_active = serializers.BooleanField(
        help_text="Whether the endpoint can be executed via the API.",
    )
    data_freshness_seconds = serializers.IntegerField(
        help_text="How fresh the data is, in seconds. One of: 900, 1800, 3600, 21600, 43200, 86400, 604800.",
    )
    endpoint_path = serializers.CharField(
        help_text="Relative API path to execute this endpoint (e.g. /api/environments/{team_id}/endpoints/{name}/run).",
    )
    url = serializers.CharField(
        allow_null=True,
        help_text="Absolute URL to execute this endpoint.",
    )
    ui_url = serializers.CharField(
        allow_null=True,
        help_text="Absolute URL to view this endpoint in the PostHog UI.",
    )
    created_at = serializers.DateTimeField(help_text="When the endpoint was created (ISO 8601).")
    updated_at = serializers.DateTimeField(help_text="When the endpoint was last updated (ISO 8601).")
    created_by = UserBasicSerializer(
        read_only=True,
        help_text="User who created the endpoint.",
    )
    is_materialized = serializers.BooleanField(
        help_text="Whether the current version's results are pre-computed to S3.",
    )
    current_version = serializers.IntegerField(help_text="Latest version number.")

    current_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of the current EndpointVersion row.",
    )

    versions_count = serializers.IntegerField(help_text="Total number of versions for this endpoint.")
    derived_from_insight = serializers.CharField(
        allow_null=True,
        help_text="Short ID of the source insight, if derived from one.",
    )
    last_executed_at = serializers.DateTimeField(
        allow_null=True,
        help_text="When this endpoint was last executed via the API (ISO 8601), or null if never executed.",
    )
    materialization = EndpointMaterializationSerializer(
        help_text="Materialization status and configuration for the current version.",
    )
    bucket_overrides = serializers.DictField(
        allow_null=True,
        help_text="Per-column bucket overrides for range variable materialization.",
    )
    columns = EndpointColumnSerializer(
        many=True,
        help_text="Column names and types from the query's SELECT clause.",
    )


class EndpointRunResponseSerializer(serializers.Serializer):
    """Response from executing an endpoint query."""

    name = serializers.CharField(help_text="URL-safe endpoint name that was executed.")
    results = serializers.ListField(
        required=False,
        help_text="Query result rows. Each row is a list of values matching the columns order.",
    )
    columns = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Column names from the query SELECT clause.",
    )
    hasMore = serializers.BooleanField(
        required=False,
        help_text="Whether more results are available beyond the limit.",
    )
    endpoint_version = serializers.IntegerField(
        required=False,
        help_text="Version number of the endpoint that was executed.",
    )


class EndpointVersionResponseSerializer(EndpointResponseSerializer):
    """Extended endpoint representation when viewing a specific version."""

    version = serializers.IntegerField(help_text="Version number.")
    version_id = serializers.UUIDField(help_text="Version unique identifier (UUID).")
    endpoint_is_active = serializers.BooleanField(
        help_text="Whether the parent endpoint is active (distinct from version.is_active).",
    )
    version_created_at = serializers.CharField(
        help_text="ISO 8601 timestamp when this version was created.",
    )
    version_updated_at = serializers.CharField(
        allow_null=True,
        help_text="ISO 8601 timestamp when this version was last updated.",
    )
    version_created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created this version.",
    )
