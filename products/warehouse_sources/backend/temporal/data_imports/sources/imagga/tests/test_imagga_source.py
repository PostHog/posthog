import pytest
from unittest import mock

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.imagga import ImaggaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.source import ImaggaSource


class TestImaggaSource:
    def setup_method(self) -> None:
        self.source = ImaggaSource()
        self.team_id = 123
        self.config = ImaggaSourceConfig(api_key="acc_test", api_secret="secret_test")

    def test_api_secret_is_a_secret_password_field(self) -> None:
        # The secret must never render as plain text or be treated as non-sensitive by the serializer.
        field = next(f for f in self.source.get_source_config.fields if f.name == "api_secret")
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — safe to surface in public docs.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["daily_usage"])
        assert [s.name for s in schemas] == ["daily_usage"]

    @pytest.mark.parametrize(
        "probe_result,expected_valid",
        [(True, True), (False, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.imagga.source.validate_imagga_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, probe_result: bool, expected_valid: bool
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("acc_test", "secret_test")
