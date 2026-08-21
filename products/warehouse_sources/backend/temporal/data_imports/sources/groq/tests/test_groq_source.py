from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.groq.source import GroqSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.groq.source"


def _make_config(api_key: str = "gsk_test") -> Any:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestGroqSource:
    @parameterized.expand(
        [
            ("valid", True, 200, True, None),
            ("invalid_key", False, 401, False, "Invalid Groq API key"),
            (
                "forbidden",
                False,
                403,
                False,
                "Your Groq API key is missing the permissions needed to sync this data",
            ),
            ("other_failure", False, 500, False, "Could not connect to Groq with the provided API key"),
            ("no_connection", False, None, False, "Could not connect to Groq with the provided API key"),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        probe_ok: bool,
        probe_status: int | None,
        expected_ok: bool,
        expected_message: str | None,
    ) -> None:
        with patch(f"{MODULE}.validate_groq_credentials", return_value=(probe_ok, probe_status)):
            ok, message = GroqSource().validate_credentials(_make_config(), team_id=1)
        assert ok is expected_ok
        assert message == expected_message

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.groq.com"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.groq.com"),
        ]
    )
    def test_non_retryable_errors_cover_auth_failures(self, _name: str, expected_key: str) -> None:
        errors = GroqSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]
