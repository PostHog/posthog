from typing import Any

from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.source import SemgrepSource


def _config(api_token: str = "token") -> Any:
    config = MagicMock()
    config.api_token = api_token
    return config


class TestValidateCredentials:
    def test_success(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.source.validate_semgrep_credentials",
            return_value=True,
        ) as mocked:
            ok, error = SemgrepSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert error is None
        mocked.assert_called_once_with("token")

    def test_failure(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.source.validate_semgrep_credentials",
            return_value=False,
        ):
            ok, error = SemgrepSource().validate_credentials(_config(), team_id=1, schema_name="sast_findings")
        assert ok is False
        assert error is not None


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
