from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.okendo import OkendoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.source import OkendoSource

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.okendo.source.validate_okendo_credentials"
)


class TestOkendoSource:
    def setup_method(self):
        self.source = OkendoSource()
        self.team_id = 123
        self.config = OkendoSourceConfig(user_id="user-1", api_key="key-1")

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.okendo.io/enterprise/reviews"),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.okendo.io/enterprise/loyalty/earning_rules",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("other_vendor", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
            ("server_error", "500 Server Error for url: https://api.okendo.io/enterprise/reviews"),
        ]
    )
    def test_non_retryable_errors_do_not_match_unrelated(self, _name, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No Okendo list endpoint filters by a created/updated timestamp, so advertising incremental
        # would ship a sync that re-reads everything while claiming a watermark it can't honor.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @parameterized.expand(
        [
            ("valid", (True, 200), None, True, None),
            ("bad_key", (False, 401), None, False, "Invalid Okendo user ID or API key"),
            ("unreachable", (False, None), None, False, "Invalid Okendo user ID or API key"),
            # 403 at connect time is a real key without review access — the user may only want the
            # loyalty tables, so blocking source creation on it would lock them out.
            ("forbidden_at_connect", (False, 403), None, True, None),
            ("forbidden_for_schema", (False, 403), "reviews", False, "Your Okendo API key does not have access"),
        ]
    )
    def test_validate_credentials(self, _name, probe_result, schema_name, expected_valid, expected_message):
        with mock.patch(VALIDATE_PATCH, return_value=probe_result) as mock_validate:
            is_valid, error_message = self.source.validate_credentials(
                self.config, self.team_id, schema_name=schema_name
            )

        assert is_valid is expected_valid
        if expected_message is None:
            assert error_message is None
        else:
            assert error_message is not None and expected_message in error_message
        mock_validate.assert_called_once_with("user-1", "key-1", "2025-02-01")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.okendo.source.okendo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_okendo_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "reviews"
        inputs.team_id = 7
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_okendo_source.call_args.kwargs
        assert kwargs["user_id"] == "user-1"
        assert kwargs["api_key"] == "key-1"
        assert kwargs["endpoint"] == "reviews"
        assert kwargs["resumable_source_manager"] is manager
        # An unpinned source must still send a version header, or every request is rejected.
        assert kwargs["api_version"] == "2025-02-01"
