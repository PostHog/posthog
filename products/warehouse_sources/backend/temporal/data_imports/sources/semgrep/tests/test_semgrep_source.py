from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.source import (
    INVALID_TOKEN_MESSAGE,
    MISSING_SCOPE_MESSAGE,
    UNREACHABLE_MESSAGE,
    SemgrepSource,
)


def _config(api_token: str = "token") -> Any:
    config = MagicMock()
    config.api_token = api_token
    return config


class TestValidateCredentials:
    def test_success(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.source.validate_semgrep_credentials",
            return_value=(True, 200),
        ) as mocked:
            ok, error = SemgrepSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert error is None
        mocked.assert_called_once_with("token")

    @parameterized.expand(
        [
            ("unauthorized", 401, INVALID_TOKEN_MESSAGE),
            ("forbidden", 403, MISSING_SCOPE_MESSAGE),
            ("server_error", 503, UNREACHABLE_MESSAGE),
            ("unreachable", None, UNREACHABLE_MESSAGE),
        ]
    )
    def test_failure(self, _name: str, status: int | None, expected_error: str) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.source.validate_semgrep_credentials",
            return_value=(False, status),
        ):
            ok, error = SemgrepSource().validate_credentials(_config(), team_id=1, schema_name="sast_findings")
        assert ok is False
        assert error == expected_error


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
