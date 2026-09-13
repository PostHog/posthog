from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.g2.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.g2.source import G2Source
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.g2 import G2SourceConfig

VALIDATE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.g2.source.validate_g2_credentials"


class TestG2Source:
    def setup_method(self) -> None:
        self.source = G2Source()
        self.team_id = 123
        self.config = G2SourceConfig(access_token="token-1", product_id="prod-1")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "G2"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/g2.png"
        # A finished source ships visible: unreleasedSource would hide it from every user.
        assert config.unreleasedSource is None

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["access_token", "product_id"]

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://data.g2.com/api/v2/categories"),
            ("forbidden", "403 Client Error: Forbidden for url: https://data.g2.com/api/v2/products/x/reviews"),
            ("missing_product_id", "G2 product ID is required to sync reviews"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("other_vendor", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
            ("server_error", "500 Server Error for url: https://data.g2.com/api/v2/products"),
        ]
    )
    def test_non_retryable_errors_do_not_match_unrelated(self, _name: str, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_are_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No G2 list endpoint documents a `sort` param, so claiming incremental would ship a
        # cursor watermark on an order the API never promised.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_products_catalog_is_opt_in(self) -> None:
        # G2's global product catalog runs into the hundreds of thousands of rows, so it must not
        # be silently enabled for every new connection.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["products"].should_sync_default is False
        assert schemas["reviews"].should_sync_default is True

    @parameterized.expand(
        [
            ("valid", (True, 200), None, True, None),
            ("bad_token", (False, 401), None, False, "Invalid G2 access token"),
            ("unreachable", (False, None), None, False, "Invalid G2 access token"),
            # 403 at connect time is a real token without every scope granted — per-endpoint
            # scoping means the account may only want a subset of tables.
            ("forbidden_at_connect", (False, 403), None, True, None),
            ("forbidden_for_schema", (False, 403), "reviews", False, "Invalid G2 access token"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: tuple[bool, int | None], schema_name, expected_valid, expected_message
    ) -> None:
        with mock.patch(VALIDATE_PATCH, return_value=probe_result) as mock_validate:
            is_valid, error_message = self.source.validate_credentials(
                self.config, self.team_id, schema_name=schema_name
            )

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("token-1", "v2")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.g2.source.g2_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_g2_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "reviews"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_g2_source.call_args.kwargs
        assert kwargs["access_token"] == "token-1"
        assert kwargs["product_id"] == "prod-1"
        assert kwargs["endpoint"] == "reviews"
        assert kwargs["resumable_source_manager"] is manager
        # An unpinned source must still send a version, or every request 404s off /api/.
        assert kwargs["api_version"] == "v2"
