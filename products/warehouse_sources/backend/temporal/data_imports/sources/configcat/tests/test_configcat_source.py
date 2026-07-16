import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.source import ConfigCatSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ConfigCatSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestConfigCatSource:
    def setup_method(self) -> None:
        self.source = ConfigCatSource()
        self.team_id = 123
        self.config = ConfigCatSourceConfig(basic_auth_username="user", basic_auth_password="pass")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CONFIGCAT

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "ConfigCat"
        assert config.label == "ConfigCat"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/configcat"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["basic_auth_username", "basic_auth_password"]

    def test_both_auth_fields_are_secret_passwords(self) -> None:
        config = self.source.get_source_config
        for name in ("basic_auth_username", "basic_auth_password"):
            field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == name)
            assert field.type == SourceFieldInputConfigType.PASSWORD
            assert field.secret is True
            assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # Both fields are secret and the base URL is hardcoded, so there is no non-secret field an
        # editor could retarget to reuse a preserved credential against another account.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["products"])
        assert len(schemas) == 1
        assert schemas[0].name == "products"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.configcat.com/v1/products",),
            ("403 Client Error: Forbidden for url: https://api.configcat.com/v1/organizations",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.configcat.com/v1/products",),
            ("429 Client Error: Too Many Requests for url: https://api.configcat.com/v1/organizations",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid ConfigCat Public API credentials"),
            (403, False, "Invalid ConfigCat Public API credentials"),
            (500, False, "ConfigCat returned HTTP 500"),
            (0, False, "Could not connect to ConfigCat: boom"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.configcat.configcat.check_access")
    def test_validate_credentials(
        self,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        message = (
            "ConfigCat returned HTTP 500"
            if status == 500
            else ("Could not connect to ConfigCat: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.configcat.source.configcat_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "products"

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["username"] == "user"
        assert kwargs["password"] == "pass"
        assert kwargs["endpoint"] == "products"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown ConfigCat schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, inputs)
