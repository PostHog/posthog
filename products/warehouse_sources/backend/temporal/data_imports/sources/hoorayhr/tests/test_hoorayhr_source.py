import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hoorayhr import (
    HoorayHRSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.source import HoorayHRSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHoorayHRSource:
    def setup_method(self) -> None:
        self.source = HoorayHRSource()
        self.team_id = 123
        self.config = HoorayHRSourceConfig(api_key="pk_test_key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HOORAYHR

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "HoorayHR"
        assert config.label == "HoorayHR"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible to users — the scaffold's unreleasedSource flag must be gone.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/hoorayhr.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hoorayhr"

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        assert [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)] == ["api_key"]
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig))
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])
        assert [s.name for s in schemas] == ["users"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # lists_tables_without_credentials=True + static get_schemas means the doc's Supported tables
        # section is populated without a live connection.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    def test_canonical_descriptions_keyed_by_endpoint_names(self) -> None:
        # A renamed endpoint would silently orphan its curated descriptions.
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.hoorayhr.io/users",
            "403 Client Error: Forbidden for url: https://api.hoorayhr.io/time-off",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        ["429 Client Error: Too Many Requests", "500 Server Error", "Connection reset by peer"],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "valid_creds, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "HoorayHR rejected the credentials. Check the API key is correct and hasn't been revoked."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.source.validate_hoorayhr_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        valid_creds: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = valid_creds
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with("pk_test_key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.source.hoorayhr_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_hoorayhr_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "time_off"

        self.source.source_for_pipeline(self.config, inputs)

        mock_hoorayhr_source.assert_called_once()
        kwargs = mock_hoorayhr_source.call_args.kwargs
        assert kwargs["api_key"] == "pk_test_key"
        assert kwargs["endpoint"] == "time_off"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
