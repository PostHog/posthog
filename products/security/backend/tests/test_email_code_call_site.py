from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.helpers.email_utils import ESPSuppressionResult
from posthog.helpers.two_factor_session import CodeBasedVerifier, add_code_based_verification_bypass

from products.security.backend.tests.helpers import exempt_rule, seed_rules


@pytest.mark.disable_mock_code_based_verifier
@patch("posthog.helpers.two_factor_session.is_dev_mode", return_value=False)
@patch("posthog.helpers.two_factor_session.is_email_available", return_value=True)
@patch("posthog.helpers.two_factor_session.is_http_email_service_available", return_value=True)
@patch("posthog.helpers.two_factor_session.posthoganalytics.feature_enabled", return_value=True)
@patch(
    "posthog.helpers.two_factor_session.check_esp_suppression",
    return_value=ESPSuppressionResult(is_suppressed=False, from_cache=False, reason=None),
)
class TestEmailCodeCallSite(SimpleTestCase):
    def _user(self, email: str) -> MagicMock:
        user = MagicMock()
        user.pk = 123
        user.email = email
        user.distinct_id = uuid4()
        return user

    def _should_send(self, email: str) -> bool:
        return CodeBasedVerifier().should_send_code_based_verification(self._user(email)).should_send

    def test_no_rule_requires_the_code(self, *_mocks: MagicMock) -> None:
        seed_rules()
        assert self._should_send("someone@example.com") is True

    def test_email_rule_skips_the_code(self, *_mocks: MagicMock) -> None:
        seed_rules(exempt_rule(targetValue="mfa.user@example.org"))
        assert self._should_send("MFA.User@example.org") is False
        assert self._should_send("mfa.user+x@example.org") is True

    def test_everyone_rule_skips_the_code(self, *_mocks: MagicMock) -> None:
        seed_rules(exempt_rule(targetType="everyone", targetValue="", expiresAt="2099-01-01T00:00:00Z"))
        assert self._should_send("anyone@example.com") is False

    def test_expired_everyone_rule_requires_the_code(self, *_mocks: MagicMock) -> None:
        seed_rules(exempt_rule(targetType="everyone", targetValue="", expiresAt="2020-01-01T00:00:00Z"))
        assert self._should_send("anyone@example.com") is True

    def test_legacy_redis_bypass_still_works(self, *_mocks: MagicMock) -> None:
        seed_rules()
        add_code_based_verification_bypass("legacy@example.com")
        assert self._should_send("legacy@example.com") is False
