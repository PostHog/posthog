import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.confluence import (
    ConfluenceResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.source import ConfluenceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ConfluenceSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestConfluenceSource:
    def setup_method(self) -> None:
        self.source = ConfluenceSource()
        self.team_id = 123
        self.config = ConfluenceSourceConfig(subdomain="acme", email="you@example.com", api_token="token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CONFLUENCE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Confluence"
        assert config.label == "Confluence"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/confluence.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["subdomain", "email", "api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_connection_host_fields_includes_subdomain(self) -> None:
        # Changing the subdomain retargets where the API token is sent.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_get_schemas_covers_all_endpoints_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No endpoint supports server-side incremental filtering.
        assert all(schema.supports_incremental is False for schema in schemas)
        assert all(schema.supports_append is False for schema in schemas)
        assert all(schema.incremental_fields == INCREMENTAL_FIELDS[schema.name] for schema in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["pages"])
        assert len(schemas) == 1
        assert schemas[0].name == "pages"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.atlassian.net/wiki/api/v2/spaces",
            "403 Client Error: Forbidden for url: https://acme.atlassian.net/wiki/api/v2/pages",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://acme.atlassian.net/wiki/api/v2/spaces",
            "429 Client Error: Too Many Requests",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            (
                (False, "Invalid Confluence credentials. Check your email and API token."),
                False,
                "Invalid Confluence credentials. Check your email and API token.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.confluence.source.validate_confluence_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, str | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(
            subdomain="acme", email="you@example.com", api_token="token", schema_name=None
        )

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ConfluenceResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.confluence.source.confluence_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_confluence_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "pages"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_confluence_source.assert_called_once()
        kwargs = mock_confluence_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["email"] == "you@example.com"
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "pages"
        assert kwargs["resumable_source_manager"] is manager
