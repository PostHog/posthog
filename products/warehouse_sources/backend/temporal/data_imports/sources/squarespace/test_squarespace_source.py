import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.squarespace import (
    SquarespaceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.source import (
    SQUARESPACE_API_VERSION_V1,
    SQUARESPACE_API_VERSION_V2,
    SquarespaceSource,
)

INCREMENTAL_ENDPOINTS = {"orders", "products", "transactions"}


class TestSquarespaceSource:
    def setup_method(self) -> None:
        self.source = SquarespaceSource()
        self.team_id = 123
        self.config = SquarespaceSourceConfig(api_key="test-key")

    def test_supported_versions_and_default(self) -> None:
        # v2 is the newest generation and the default new sources start on; v1 stays supported so
        # existing pins keep resolving. The generic registry test only checks invariants — this
        # pins the specific labels so a reorder or a default flip-back is caught.
        assert self.source.supported_versions == (SQUARESPACE_API_VERSION_V1, SQUARESPACE_API_VERSION_V2)
        assert self.source.default_version == SQUARESPACE_API_VERSION_V2

    @pytest.mark.parametrize(
        "mock_return, schema_name, expected_valid, expected_has_message",
        [
            ((True, False), None, True, False),
            ((False, False), None, False, True),  # 401 bad token
            ((False, True), None, True, False),  # 403 at source-create -> accepted
            ((False, True), "orders", False, True),  # 403 for a specific schema -> rejected
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.source.validate_squarespace_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, bool],
        schema_name: str | None,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert is_valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(self.config.api_key, schema_name)
