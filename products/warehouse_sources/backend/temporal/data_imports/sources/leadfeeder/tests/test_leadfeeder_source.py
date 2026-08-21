from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import VersionDeprecation
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.leadfeeder import (
    LeadfeederSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.settings import (
    LEADFEEDER_API_2026_08_07,
    LEADFEEDER_API_LEGACY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source import LeadfeederSource


class TestLeadfeederSource:
    def setup_method(self) -> None:
        self.source = LeadfeederSource()
        self.team_id = 123
        self.config = LeadfeederSourceConfig(api_token="token", start_date="2024-01-01")

    def test_version_metadata_defaults_to_unified_and_deprecates_legacy(self) -> None:
        # New sources land on the unified Dealfront API; the legacy Token API is advisory-deprecated
        # (no announced sunset), which is why existing pins are not migrated automatically.
        assert self.source.supported_versions == (LEADFEEDER_API_LEGACY, LEADFEEDER_API_2026_08_07)
        assert self.source.default_version == LEADFEEDER_API_2026_08_07
        assert self.source.deprecated_versions == (VersionDeprecation(version=LEADFEEDER_API_LEGACY, sunset_at=None),)

    @parameterized.expand(
        [
            (True, True, None),
            (
                False,
                False,
                "Unable to verify your Leadfeeder API token. Check that the token is correct and that Leadfeeder is reachable.",
            ),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source.validate_leadfeeder_credentials"
    )
    def test_validate_credentials(
        self, mock_return: bool, expected_valid: bool, expected_message: str | None, mock_validate: mock.MagicMock
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert error_message == expected_message
        # No pin at creation time resolves to the default (unified) version.
        mock_validate.assert_called_once_with("token", LEADFEEDER_API_2026_08_07)

    @parameterized.expand([(None, LEADFEEDER_API_2026_08_07), (LEADFEEDER_API_LEGACY, LEADFEEDER_API_LEGACY)])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.source.validate_leadfeeder_credentials"
    )
    def test_validate_credentials_probes_under_the_pinned_version(
        self, pin: str | None, expected_version: str, mock_validate: mock.MagicMock
    ) -> None:
        # A legacy-pinned source must probe the legacy API, not the resolved default — otherwise a
        # valid legacy token would fail validation against the unified endpoint.
        mock_validate.return_value = True
        self.source.validate_credentials(self.config, self.team_id, api_version=pin)
        mock_validate.assert_called_once_with("token", expected_version)
