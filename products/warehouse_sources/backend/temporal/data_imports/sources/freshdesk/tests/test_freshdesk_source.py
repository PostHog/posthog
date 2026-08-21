from typing import Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.source import FreshdeskSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshdesk import (
    FreshdeskSourceConfig,
)

PATCH_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.source.validate_freshdesk_credentials"
)


class TestFreshdeskSource:
    def setup_method(self) -> None:
        self.source = FreshdeskSource()
        self.team_id = 1
        self.config = FreshdeskSourceConfig(subdomain="acme", api_key="key")

    @pytest.mark.parametrize(
        "subdomain, status, schema_name, expected_valid",
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
        self, subdomain: str, status: Optional[int], schema_name: Optional[str], expected_valid: bool
    ) -> None:
        config = FreshdeskSourceConfig(subdomain=subdomain, api_key="key")
        with mock.patch(PATCH_VALIDATE, return_value=status) as mock_validate:
            is_valid, _ = self.source.validate_credentials(config, self.team_id, schema_name)

        assert is_valid is expected_valid
        if "!" in subdomain or " " in subdomain:
            mock_validate.assert_not_called()
