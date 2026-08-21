from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.source import (
    CloudzeroSource,
    _parse_group_by,
)


def _config(
    api_key: str = "key", granularity: str = "daily", cost_type: str = "real_cost", group_by: str | None = None
) -> Any:
    config = MagicMock()
    config.api_key = api_key
    config.granularity = granularity
    config.cost_type = cost_type
    config.group_by = group_by
    return config


class TestParseGroupBy:
    @parameterized.expand(
        [
            ("none", None, []),
            ("empty_string", "", []),
            ("single", "service", ["service"]),
            ("multiple", "service,account", ["service", "account"]),
            ("whitespace_and_blank_entries", " service , , account ", ["service", "account"]),
        ]
    )
    def test_parse_group_by(self, _name: str, raw: str | None, expected: list[str]) -> None:
        assert _parse_group_by(raw) == expected


class TestSourceConfig:
    def test_api_version_metadata(self) -> None:
        assert CloudzeroSource.supported_versions == ("v2",)
        assert CloudzeroSource.default_version == "v2"
        assert CloudzeroSource.api_docs_url.startswith("https://")


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", True, (True, None)),
            ("invalid", False, (False, "Invalid credentials")),
        ]
    )
    def test_plumbs_transport_result(
        self, _name: str, transport_result: bool, expected: tuple[bool, str | None]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cloudzero.source.validate_cloudzero_credentials",
            return_value=transport_result,
        ) as mocked:
            assert CloudzeroSource().validate_credentials(_config(), team_id=1) == expected
        mocked.assert_called_once_with("key")
