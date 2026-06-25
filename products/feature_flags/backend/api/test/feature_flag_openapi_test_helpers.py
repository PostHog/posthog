"""Shared helpers for ``test_feature_flag_openapi.py`` — not a test module itself."""

from rest_framework import serializers

from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer

# Runtime FeatureFlagSerializer fields that are writable but intentionally absent from the
# agent-facing ``*RequestSchemaSerializer`` doc serializers (and therefore the OpenAPI spec,
# generated types, and MCP tools). Each omission is deliberate: to expose a field, add it to
# both doc serializers and to ``tools.yaml`` include_params; to keep it hidden, list it here
# with a reason.
FEATURE_FLAG_REQUEST_SCHEMA_EXCLUDED_RUNTIME_FIELDS: frozenset[str] = frozenset(
    {
        "_create_in_folder",  # create-only write_only helper for folder placement
        "_should_create_usage_dashboard",  # create-only write_only internal toggle
        "analytics_dashboards",  # relational link managed via dashboards, not the flag create/update surface
        "created_at",  # server-managed timestamp, not agent-facing
        "creation_context",  # write_only origin-product marker set by internal callers
        "deleted",  # soft-delete handled via the DELETE endpoint, not the create/update body
        "has_encrypted_payloads",  # server-managed, derived from payload encryption
        "has_enriched_analytics",  # internal analytics flag, not agent-facing
        "last_called_at",  # server-managed usage timestamp, not agent-facing
        "performed_rollback",  # internal rollback state
        "rollback_conditions",  # legacy rollback config, not agent-facing
        "version",  # server-managed optimistic-concurrency counter
    }
)


def feature_flag_request_schema_runtime_field_names() -> frozenset[str]:
    serializer = FeatureFlagSerializer()
    writable: set[str] = set()
    for name, field in serializer.fields.items():
        if isinstance(field, serializers.SerializerMethodField):
            continue
        if getattr(field, "read_only", False):
            continue
        writable.add(name)
    return frozenset(writable - FEATURE_FLAG_REQUEST_SCHEMA_EXCLUDED_RUNTIME_FIELDS)
