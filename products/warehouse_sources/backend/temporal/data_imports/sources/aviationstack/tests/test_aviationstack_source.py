from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.source import AviationstackSource


def _make_config(access_key: str = "key") -> Any:
    config = MagicMock()
    config.access_key = access_key
    return config


class TestAviationstackSource:
    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid aviationstack access key"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_ok: bool, expected_message: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.source.validate_aviationstack_credentials",
            return_value=probe_result,
        ):
            ok, message = AviationstackSource().validate_credentials(_make_config(), team_id=1)
        assert ok is expected_ok
        assert message == expected_message

    @parameterized.expand(
        [
            ("http_unauthorized", "401 Client Error: Unauthorized for url: https://api.aviationstack.com"),
            ("body_invalid_key", "aviationstack API error [invalid_access_key]"),
            ("body_usage_limit", "aviationstack API error [usage_limit_reached]"),
            ("body_function_restricted", "aviationstack API error [function_access_restricted]"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = AviationstackSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]
