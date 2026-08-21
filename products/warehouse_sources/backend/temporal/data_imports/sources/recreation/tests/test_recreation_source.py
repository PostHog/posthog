from typing import Optional

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recreation import (
    RecreationSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.source import RecreationSource


class TestRecreationSource:
    def setup_method(self) -> None:
        self.source = RecreationSource()
        self.config = RecreationSourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_error_fragment"),
        [
            (200, True, None),
            (401, False, "Invalid RIDB API key"),
            (403, False, "Invalid RIDB API key"),
            (500, False, "unexpected response"),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_error_fragment: Optional[str]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.recreation.recreation.make_tracked_session"
        ) as mock_session_factory:
            mock_session_factory.return_value.get.return_value.status_code = status_code
            valid, error = self.source.validate_credentials(self.config, team_id=1)

        assert valid is expected_valid
        if expected_error_fragment is None:
            assert error is None
        else:
            assert error is not None and expected_error_fragment in error
