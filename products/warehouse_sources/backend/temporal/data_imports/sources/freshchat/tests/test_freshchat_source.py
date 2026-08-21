from typing import Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.source import FreshchatSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshchat import (
    FreshchatSourceConfig,
)

PATCH_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.source.validate_freshchat_credentials"
)


class TestFreshchatSource:
    def setup_method(self) -> None:
        self.source = FreshchatSource()
        self.team_id = 1
        self.config = FreshchatSourceConfig(domain="acme.freshchat.com", api_key="key")

    @pytest.mark.parametrize(
        "domain, status, schema_name, expected_valid, expect_probe",
        [
            ("acme.freshchat.com", 200, None, True, True),
            ("acme.freshchat.com", 403, None, True, True),  # missing scope at source-create is accepted
            ("acme.freshchat.com", 403, "agents", False, True),  # missing scope for a specific schema fails
            ("acme.freshchat.com", 401, None, False, True),
            ("acme.freshchat.com", None, None, False, True),  # connection error
            ("not a domain!", 200, None, False, False),  # domain regex rejects before probing
            # Non-Freshworks hosts are refused before probing — the stored token must never be
            # sent to a customer-chosen internal host (SSRF).
            ("metadata.google.internal", 200, None, False, False),
            ("api.default.svc.cluster.local", 200, None, False, False),
            ("evilfreshchat.com", 200, None, False, False),  # suffix match must not accept lookalikes
        ],
    )
    def test_validate_credentials(
        self,
        domain: str,
        status: Optional[int],
        schema_name: Optional[str],
        expected_valid: bool,
        expect_probe: bool,
    ) -> None:
        config = FreshchatSourceConfig(domain=domain, api_key="key")
        with mock.patch(PATCH_VALIDATE, return_value=status) as mock_validate:
            is_valid, _ = self.source.validate_credentials(config, self.team_id, schema_name)

        assert is_valid is expected_valid
        if not expect_probe:
            mock_validate.assert_not_called()
