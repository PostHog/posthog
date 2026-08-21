import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.greenhouse import (
    GreenhouseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source import GreenhouseSource

INCREMENTAL_ENDPOINTS = {
    "candidates",
    "applications",
    "jobs",
    "job_posts",
    "offers",
    "scorecards",
    "scheduled_interviews",
    "users",
}
FULL_REFRESH_ENDPOINTS = {"departments", "offices", "sources", "rejection_reasons", "close_reasons"}


class TestGreenhouseSource:
    def setup_method(self) -> None:
        self.source = GreenhouseSource()
        self.team_id = 123
        self.config = GreenhouseSourceConfig(api_key="test_api_key", client_id="cid", client_secret="csecret")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Greenhouse"
        assert config.label == "Greenhouse"
        assert config.releaseStatus == "alpha"
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/greenhouse.png"

        fields = {field.name: field for field in config.fields if isinstance(field, SourceFieldInputConfig)}
        assert set(fields) == {"client_id", "client_secret", "api_key"}
        # No field is required at the form level: v3 takes the OAuth client pair and v1 the API key,
        # so `validate_credentials` enforces whichever the resolved version needs.
        assert not any(field.required for field in fields.values())
        assert {name for name, field in fields.items() if field.secret} == {"client_secret", "api_key"}
        assert fields["client_secret"].type == SourceFieldInputConfigType.PASSWORD

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.validate_greenhouse_credentials"
    )
    def test_validate_credentials_at_source_create_accepts_forbidden(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        is_valid, error = self.source.validate_credentials(self.config, self.team_id, schema_name=None)

        assert is_valid is True
        assert error is None
        mock_validate.assert_called_once_with(
            "v3", api_key="test_api_key", client_id="cid", client_secret="csecret", accept_forbidden=True
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.validate_greenhouse_credentials"
    )
    def test_validate_credentials_per_schema_probes_endpoint_path(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        self.source.validate_credentials(self.config, self.team_id, schema_name="candidates")

        mock_validate.assert_called_once_with(
            "v3",
            api_key="test_api_key",
            client_id="cid",
            client_secret="csecret",
            path="/candidates",
            accept_forbidden=False,
        )

    @pytest.mark.parametrize(
        "pinned_version, expected_version, expected_path",
        [
            (None, "v3", "/interviews"),
            ("v3", "v3", "/interviews"),
            # A v1-pinned source must be probed on v1, not on the (newer) default.
            ("v1", "v1", "/scheduled_interviews"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.source.validate_greenhouse_credentials"
    )
    def test_validate_credentials_probes_the_pinned_version(
        self,
        mock_validate: mock.MagicMock,
        pinned_version: str | None,
        expected_version: str,
        expected_path: str,
    ) -> None:
        mock_validate.return_value = (True, None)

        self.source.validate_credentials(
            self.config, self.team_id, schema_name="scheduled_interviews", api_version=pinned_version
        )

        assert mock_validate.call_args.args[0] == expected_version
        assert mock_validate.call_args.kwargs["path"] == expected_path
