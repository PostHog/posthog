import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.brevo import (
    BREVO_INVALID_API_KEY_MESSAGE,
    BREVO_MISSING_PERMISSIONS_MESSAGE,
    BREVO_SMTP_KEY_MESSAGE,
    BREVO_UNREACHABLE_MESSAGE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brevo.source import BrevoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.brevo import BrevoSourceConfig


class TestBrevoSource:
    @pytest.mark.parametrize(
        ("api_key", "answer", "expected_ok", "expected_msg"),
        [
            ("xkeysib-test", ScriptedResponse(json={}), True, None),
            ("xkeysib-test", ScriptedResponse(status=401), False, BREVO_INVALID_API_KEY_MESSAGE),
            ("xsmtpsib-test", ScriptedResponse(status=401), False, BREVO_SMTP_KEY_MESSAGE),
            ("xkeysib-test", ScriptedResponse(status=403), False, BREVO_MISSING_PERMISSIONS_MESSAGE),
            ("xkeysib-test", ScriptedResponse(status=429), False, BREVO_UNREACHABLE_MESSAGE),
            ("xkeysib-test", ScriptedResponse(status=503), False, BREVO_UNREACHABLE_MESSAGE),
            ("xkeysib-test", OSError("network down"), False, BREVO_UNREACHABLE_MESSAGE),
        ],
    )
    def test_validate_credentials(
        self, api_key: str, answer: ScriptedResponse | Exception, expected_ok: bool, expected_msg: str | None
    ) -> None:
        with scripted_network([answer]):
            ok, msg = BrevoSource().validate_credentials(BrevoSourceConfig(api_key=api_key), team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg
