from typing import Any, Optional

from unittest.mock import patch

import structlog
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.front import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.front.source import FrontSource

logger = structlog.get_logger()


def _config(api_token: str = "tok") -> Any:
    return FrontSource().parse_config({"api_token": api_token})


class TestFrontSource:
    @parameterized.expand(
        [
            # (status_at_create, expected_ok) — source-create probe accepts everything but 401
            ("valid", True, None),
            ("invalid", False, "Invalid Front API token. Please reconnect with a valid token."),
        ]
    )
    def test_validate_credentials_at_source_create(self, _name: str, ok: bool, msg: Optional[str]) -> None:
        with patch.object(source_module, "validate_front_credentials", return_value=(ok, msg)) as mock_validate:
            result = FrontSource().validate_credentials(_config(), team_id=1, schema_name=None)
        assert result == (ok, msg)
        # source-create probes /teammates with require_scope=False
        mock_validate.assert_called_once_with("tok", "/teammates", require_scope=False)

    def test_validate_credentials_for_schema_requires_scope(self) -> None:
        with patch.object(source_module, "validate_front_credentials", return_value=(True, None)) as mock_validate:
            FrontSource().validate_credentials(_config(), team_id=1, schema_name="tags")
        mock_validate.assert_called_once_with("tok", "/tags", require_scope=True)
