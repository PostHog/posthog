import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.propertyware import (
    PropertywareSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.source import PropertywareSource


class TestPropertywareSource:
    def setup_method(self) -> None:
        self.source = PropertywareSource()
        self.team_id = 123
        self.config = PropertywareSourceConfig(client_id="cid", client_secret="secret", system_id="org-1")

    @pytest.mark.parametrize(
        "status, schema_name, expected_ok",
        [
            (200, None, True),
            (200, "Portfolios", True),
            (403, None, True),  # a key scoped to fewer entities is tolerated at source-create
            (403, "Bills", False),  # but rejected when validating a schema it can't reach
            (401, None, False),
            (500, None, False),
            (None, None, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.source.validate_propertyware_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        status: int | None,
        schema_name: str | None,
        expected_ok: bool,
    ) -> None:
        mock_validate.return_value = status
        ok, _ = self.source.validate_credentials(self.config, self.team_id, schema_name)
        assert ok is expected_ok
