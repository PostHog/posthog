import datetime

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harvey import HarveySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source import HarveySource


class TestHarveySource:
    def setup_method(self) -> None:
        self.source = HarveySource()
        self.team_id = 123
        self.config = HarveySourceConfig(api_key="test-token", region="us")

    def test_v1_is_deprecated_with_vendor_sunset_and_default_is_v2(self) -> None:
        # New sources start on v2; v1 stays supported so already-pinned rows keep resolving to the
        # unchanged v2 wire, but it carries Harvey's 2025-06-30 sunset date so the generic
        # in-product deprecation warning fires.
        assert self.source.default_version == "v2"
        assert set(self.source.supported_versions) == {"v1", "v2"}

        deprecation = self.source.get_version_deprecation("v1")
        assert deprecation is not None
        assert deprecation.sunset_at == datetime.date(2025, 6, 30)
        assert self.source.get_version_deprecation("v2") is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.validate_harvey_credentials"
    )
    def test_validate_credentials_success(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with("test-token", "us")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.validate_harvey_credentials"
    )
    def test_validate_credentials_failure(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Harvey API token"

    @parameterized.expand(
        [
            ("has_access", None, True),
            ("no_access", "Your API token does not have permission for this endpoint.", False),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.check_endpoint_access")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.validate_harvey_credentials"
    )
    def test_validate_credentials_with_schema_name_checks_endpoint_access(
        self,
        _name: str,
        access_reason: str | None,
        expected_valid: bool,
        mock_validate: mock.MagicMock,
        mock_access: mock.MagicMock,
    ) -> None:
        mock_validate.return_value = True
        mock_access.return_value = access_reason

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name="audit_logs")

        assert is_valid is expected_valid
        assert error_message == access_reason
        mock_access.assert_called_once_with("test-token", "us", "audit_logs")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.harvey.source.check_endpoint_access")
    def test_get_endpoint_permissions(self, mock_access: mock.MagicMock) -> None:
        mock_access.side_effect = lambda api_key, region, endpoint: (
            "missing permission" if endpoint == "vault_projects" else None
        )

        permissions = self.source.get_endpoint_permissions(
            self.config, self.team_id, ["audit_logs", "vault_projects", "unknown_endpoint"]
        )

        assert permissions == {
            "audit_logs": None,
            "vault_projects": "missing permission",
            "unknown_endpoint": None,
        }
