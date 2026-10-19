import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.square import SquareSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.square.source import SquareSource
from products.warehouse_sources.backend.temporal.data_imports.sources.square.square import SquareCredentialProbe


class TestSquareSource:
    def setup_method(self) -> None:
        self.source = SquareSource()
        self.team_id = 123
        self.config = SquareSourceConfig(access_token="EAAA-test", environment="production")

    @pytest.mark.parametrize(
        "mock_return, schema_name, api_version, expected_valid, expected_has_message, expected_version",
        [
            ((True, False), None, None, True, False, "2026-09-16"),  # pre-creation probe -> default version
            ((True, False), "payments", "v2", True, False, "v2"),  # pinned row -> its own version
            ((False, False), None, None, False, True, "2026-09-16"),  # 401 bad token
            ((False, True), None, None, True, False, "2026-09-16"),  # 403 at source-create -> accepted
            ((False, True), "payments", None, False, True, "2026-09-16"),  # 403 for a specific schema -> rejected
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.square.source.validate_square_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, bool],
        schema_name: str | None,
        api_version: str | None,
        expected_valid: bool,
        expected_has_message: bool,
        expected_version: str,
    ) -> None:
        mock_validate.return_value = SquareCredentialProbe(is_valid=mock_return[0], is_forbidden=mock_return[1])
        is_valid, message = self.source.validate_credentials(
            self.config, self.team_id, schema_name=schema_name, api_version=api_version
        )
        assert is_valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(
            self.config.access_token, self.config.environment, expected_version, schema_name
        )
