import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.source import BrevoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.brevo import BrevoSourceConfig


def _config() -> BrevoSourceConfig:
    return BrevoSourceConfig(api_key="test-key")


class TestBrevoSource:
    @pytest.mark.parametrize(
        ("valid", "expected_ok", "expected_msg"),
        [(True, True, None), (False, False, "Invalid Brevo API key")],
    )
    def test_validate_credentials(self, valid: bool, expected_ok: bool, expected_msg: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.brevo.source.validate_brevo_credentials",
            return_value=valid,
        ):
            ok, msg = BrevoSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg
