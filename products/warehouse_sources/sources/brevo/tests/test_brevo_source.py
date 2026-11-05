import pytest

from products.warehouse_sources.sources.brevo._config import BrevoSourceConfig
from products.warehouse_sources.sources.brevo.brevo import (
    BREVO_INVALID_API_KEY_MESSAGE,
    BREVO_MISSING_PERMISSIONS_MESSAGE,
    BREVO_SMTP_KEY_MESSAGE,
    BREVO_UNREACHABLE_MESSAGE,
)
from products.warehouse_sources.sources.brevo.source import BrevoSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network

# The shared session retries a connection error, 429 and 5xx three times before it gives up.
_RETRIED_ATTEMPTS = 4


class TestBrevoSource:
    @pytest.mark.parametrize(
        ("api_key", "answers", "expected_ok", "expected_msg"),
        [
            ("xkeysib-test", [ScriptedResponse(json={})], True, None),
            ("xkeysib-test", [ScriptedResponse(status=401)], False, BREVO_INVALID_API_KEY_MESSAGE),
            ("xsmtpsib-test", [ScriptedResponse(status=401)], False, BREVO_SMTP_KEY_MESSAGE),
            ("xkeysib-test", [ScriptedResponse(status=403)], False, BREVO_MISSING_PERMISSIONS_MESSAGE),
            ("xkeysib-test", [ScriptedResponse(status=404)], False, BREVO_INVALID_API_KEY_MESSAGE),
            ("xkeysib-test", [ScriptedResponse(status=429)] * _RETRIED_ATTEMPTS, False, BREVO_UNREACHABLE_MESSAGE),
            ("xkeysib-test", [ScriptedResponse(status=503)] * _RETRIED_ATTEMPTS, False, BREVO_UNREACHABLE_MESSAGE),
            ("xkeysib-test", [OSError("network down")] * _RETRIED_ATTEMPTS, False, BREVO_UNREACHABLE_MESSAGE),
        ],
    )
    def test_validate_credentials(
        self, api_key: str, answers: list[ScriptedResponse | Exception], expected_ok: bool, expected_msg: str | None
    ) -> None:
        with scripted_network(answers) as network:
            ok, msg = BrevoSource().validate_credentials(BrevoSourceConfig(api_key=api_key), team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg
        assert len(network.requests_log) == len(answers)
