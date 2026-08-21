from typing import Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.source import FreshserviceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshservice import (
    FreshserviceSourceConfig,
)

PATCH_VALIDATE = "products.warehouse_sources.backend.temporal.data_imports.sources.freshservice.source.validate_freshservice_credentials"


class TestFreshserviceSource:
    def setup_method(self) -> None:
        self.source = FreshserviceSource()
        self.team_id = 1
        self.config = FreshserviceSourceConfig(domain="acme", api_key="key")

    @pytest.mark.parametrize(
        "domain, status, schema_name, expected_valid",
        [
            ("acme", 200, None, True),
            ("acme", 403, None, True),  # missing scope at source-create is accepted
            ("acme", 403, "tickets", False),  # missing scope for a specific schema fails
            ("acme", 401, None, False),
            ("acme", None, None, False),  # connection error
            ("invalid domain!", 200, None, False),  # domain regex rejects before probing
        ],
    )
    def test_validate_credentials(
        self, domain: str, status: Optional[int], schema_name: Optional[str], expected_valid: bool
    ) -> None:
        config = FreshserviceSourceConfig(domain=domain, api_key="key")
        with mock.patch(PATCH_VALIDATE, return_value=status) as mock_validate:
            is_valid, _ = self.source.validate_credentials(config, self.team_id, schema_name)

        assert is_valid is expected_valid
        if "!" in domain or " " in domain:
            mock_validate.assert_not_called()
