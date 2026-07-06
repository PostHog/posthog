from parameterized import parameterized

from products.feature_flags.backend.api.feature_flag import (
    FeatureFlagCreateRequestSchemaSerializer,
    FeatureFlagPartialUpdateRequestSchemaSerializer,
)
from products.feature_flags.backend.api.test.feature_flag_openapi_test_helpers import (
    feature_flag_request_schema_runtime_field_names,
)


class TestFeatureFlagRequestSchemaContract:
    @parameterized.expand(
        [
            ("create", FeatureFlagCreateRequestSchemaSerializer),
            ("partial_update", FeatureFlagPartialUpdateRequestSchemaSerializer),
        ]
    )
    def test_request_schema_covers_agent_facing_runtime_fields(self, _name, schema_serializer) -> None:
        runtime_fields = feature_flag_request_schema_runtime_field_names()
        documented = frozenset(schema_serializer().fields.keys())
        missing = runtime_fields - documented
        assert not missing, (
            f"{schema_serializer.__name__} must document every agent-facing FeatureFlagSerializer input. "
            f"Missing: {sorted(missing)}. extend_schema(request=...) replaces the whole request body, so a "
            "writable runtime field absent here never reaches the OpenAPI spec or MCP tools. Add the field to "
            "both doc serializers and tools.yaml include_params to expose it, or to "
            "FEATURE_FLAG_REQUEST_SCHEMA_EXCLUDED_RUNTIME_FIELDS with a reason to keep it hidden."
        )
