import pytest
from unittest.mock import patch

from sources.brevo._config import BrevoSourceConfig
from sources.brevo.source import BREVO_INVALID_API_KEY_MESSAGE, BrevoSource


def _config() -> BrevoSourceConfig:
    return BrevoSourceConfig(api_key="test-key")


class TestBrevoSource:
    @pytest.mark.parametrize(
        ("valid", "expected_ok", "expected_msg"),
        [
            (True, True, None),
            (False, False, BREVO_INVALID_API_KEY_MESSAGE),
        ],
    )
    def test_validate_credentials(self, valid: bool, expected_ok: bool, expected_msg: str | None) -> None:
        with patch(
            "sources.brevo.source.validate_brevo_credentials",
            return_value=valid,
        ):
            ok, msg = BrevoSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg
