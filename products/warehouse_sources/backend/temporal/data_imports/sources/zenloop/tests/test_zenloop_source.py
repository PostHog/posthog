import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zenloop import (
    ZenloopSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source import ZenloopSource


class TestZenloopSource:
    def setup_method(self) -> None:
        self.source = ZenloopSource()
        self.team_id = 123
        self.config = ZenloopSourceConfig(api_token="zenloop-token")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Zenloop"
        assert config.label == "Zenloop"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/zenloop"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret token itself; the base URL is hardcoded and the account is
        # implicit in the token. There is no non-secret field that retargets where the token is sent.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_documented_tables_render_for_public_docs(self) -> None:
        # Exercises the credential-free catalog path used by the posthog.com docs.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.zenloop.com/v1/surveys?page=1&per_page=50",
            "403 Client Error: Forbidden for url: https://api.zenloop.com/v1/properties?page=2&per_page=50",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.zenloop.com/v1/surveys",
            "HTTPSConnectionPool(host='api.zenloop.com', port=443): Read timed out.",
            "429 Client Error: Too Many Requests for url: https://api.zenloop.com/v1/survey_groups",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Zenloop API token"),
            (403, False, "Invalid Zenloop API token"),
            (500, False, "Zenloop returned HTTP 500"),
            (0, False, "Could not connect to Zenloop: boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "Zenloop returned HTTP 500"
            if status == 500
            else ("Could not connect to Zenloop: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source.check_access")
    def test_validate_credentials_probes_the_account_token(self, mock_check: mock.MagicMock) -> None:
        # The API token is account-wide, so validation probes the token, not a per-schema scope.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="properties")
        mock_check.assert_called_once_with("zenloop-token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source.zenloop_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_zenloop_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "surveys"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_zenloop_source.assert_called_once()
        kwargs = mock_zenloop_source.call_args.kwargs
        assert kwargs["api_token"] == "zenloop-token"
        assert kwargs["endpoint"] == "surveys"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Zenloop schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
