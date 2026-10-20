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
    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert GroqSource.lists_tables_without_credentials is True

    @parameterized.expand(
        [
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
