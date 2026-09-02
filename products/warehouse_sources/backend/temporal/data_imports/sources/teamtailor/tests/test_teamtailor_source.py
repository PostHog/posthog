import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamtailor import (
    TeamtailorSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.source import TeamtailorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.teamtailor import (
    API_VERSION_20240404,
    API_VERSION_20240904,
)


class TestTeamtailorSource:
    def setup_method(self) -> None:
        self.source = TeamtailorSource()
        self.team_id = 123
        self.config = TeamtailorSourceConfig(api_key="tt-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Teamtailor"
        assert config.label == "Teamtailor"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/teamtailor"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key"]

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API key; the base URL is hardcoded, so there is no non-secret
        # field an editor could retarget to reuse a preserved key against another account.
        assert self.source.connection_host_fields == []

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.teamtailor.com/v1/candidates?page%5Bsize%5D=30",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.teamtailor.com/v1/jobs?page%5Bsize%5D=30"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.teamtailor.com/v1/candidates",
            ),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.teamtailor.com/v1/jobs"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_version_declarations_default_to_current(self) -> None:
        # New sources start on the newest stable version; the legacy pin stays selectable.
        assert self.source.supported_versions == (API_VERSION_20240404, API_VERSION_20240904)
        assert self.source.default_version == API_VERSION_20240904

    @parameterized.expand(
        [
            ("no_pin_uses_default", None, API_VERSION_20240904),
            ("legacy_pin_honored", API_VERSION_20240404, API_VERSION_20240404),
            ("current_pin_honored", API_VERSION_20240904, API_VERSION_20240904),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.teamtailor.source.teamtailor_source")
    def test_source_for_pipeline_threads_resolved_version(
        self, _name: str, pin: str | None, expected_version: str, mock_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "candidates"
        inputs.api_version = pin
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "tt-key"
        assert kwargs["endpoint"] == "candidates"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["api_version"] == expected_version

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Teamtailor schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
