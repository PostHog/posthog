from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.source import JumpcloudSource


def _config(api_key: str = "key", org_id: str | None = None, region: str = "us") -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.org_id = org_id
    config.region = region
    return config


class TestSourceConfig:
    def test_connection_host_fields_force_secret_reentry_on_retarget(self) -> None:
        # Changing org_id or region retargets the stored API key (different organization's
        # data, or a different regional host), so both must force re-entering the key.
        assert JumpcloudSource().connection_host_fields == ["org_id", "region"]


class TestGetSchemas:
    def test_names_filter(self) -> None:
        schemas = JumpcloudSource().get_schemas(_config(), team_id=1, names=["users", "events"])
        assert {s.name for s in schemas} == {"users", "events"}


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized_console",
                "401 Client Error: Unauthorized for url: https://console.jumpcloud.com/api/systemusers?limit=100",
            ),
            (
                "forbidden_insights",
                "403 Client Error: Forbidden for url: https://api.jumpcloud.com/insights/directory/v1/events",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = JumpcloudSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='console.jumpcloud.com', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://console.jumpcloud.com/api/systems",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://console.jumpcloud.com/api/systemusers",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = JumpcloudSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))
