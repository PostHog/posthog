import datetime

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harvey import HarveySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.settings import ENDPOINTS
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

    def test_connection_host_fields_includes_region(self) -> None:
        # `region` selects the host the stored API token is sent to, so editing it must re-require the secret.
        assert self.source.connection_host_fields == ["region"]

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            # Audit logs are immutable, so only append is offered.
            ("audit_logs", "audit_logs", False, True, "timestamp"),
            ("usage_history", "usage_history", True, True, "utc_time"),
            ("query_history", "query_history", True, True, "utc_time"),
            ("client_matters", "client_matters", False, False, None),
            ("vault_projects", "vault_projects", False, False, None),
        ]
    )
    def test_get_schemas_sync_modes(
        self,
        _name: str,
        endpoint: str,
        supports_incremental: bool,
        supports_append: bool,
        incremental_field: str | None,
    ) -> None:
        (schema,) = self.source.get_schemas(self.config, self.team_id, names=[endpoint])

        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_append
        if incremental_field is None:
            assert schema.incremental_fields == []
        else:
            assert [f["field"] for f in schema.incremental_fields] == [incremental_field]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

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
