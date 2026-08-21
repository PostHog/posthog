from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.terraformcloud import (
    TerraformCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source import TerraformCloudSource


def _config(api_token: str = "test-token", organization: str = "acme") -> TerraformCloudSourceConfig:
    return TerraformCloudSourceConfig.from_dict({"api_token": api_token, "organization": organization})


class TestTerraformCloudSource:
    @parameterized.expand(
        [
            ("bad org/../path", False),
            ("has space", False),
            ("", False),
        ]
    )
    def test_validate_credentials_rejects_invalid_org_names_without_network(self, organization: str, _: bool) -> None:
        # The org name lands in a URL path; a malformed value must be rejected before any request.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source.validate_terraform_cloud_credentials"
        ) as probe:
            ok, message = TerraformCloudSource().validate_credentials(_config(organization=organization), team_id=1)
        assert ok is False
        assert message is not None
        probe.assert_not_called()

    def test_validate_credentials_delegates_probe(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.terraform_cloud.source.validate_terraform_cloud_credentials",
            return_value=(True, None),
        ) as probe:
            assert TerraformCloudSource().validate_credentials(_config(), team_id=1) == (True, None)
        probe.assert_called_once_with("test-token", "acme")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://app.terraform.io/api/v2/workspaces/ws-1/runs",),
            ("403 Client Error: Forbidden for url: https://app.terraform.io/api/v2/organizations/acme/teams",),
        ]
    )
    def test_non_retryable_errors_match_credential_failures(self, raised_message: str) -> None:
        # A revoked token must permanently fail the sync rather than retry forever; the matcher
        # keys on the stable status text + host, so real HTTPError strings match.
        errors = TerraformCloudSource().get_non_retryable_errors()
        assert any(pattern in raised_message and friendly for pattern, friendly in errors.items())
