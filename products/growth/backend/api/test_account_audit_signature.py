from types import SimpleNamespace

import time_machine

from django.test import SimpleTestCase

from products.growth.backend.api.account_audits import AccountAuditStartViewSet


class TestAccountAuditSignature(SimpleTestCase):
    @time_machine.travel("2021-02-25T15:02:10Z", tick=False)
    def test_accepts_standard_webhooks_reference_signature(self) -> None:
        credential = SimpleNamespace(signing_secret="whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
        assert AccountAuditStartViewSet._valid_signature(
            credential,
            "msg_p5jXN8AQM9LWM0D4loKWxJek",
            "1614265330",
            "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
            b'{"test": 2432232314}',
        )
        assert not AccountAuditStartViewSet._valid_signature(
            credential,
            "msg_p5jXN8AQM9LWM0D4loKWxJek",
            "1614265330",
            "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
            b'{"test": 2432232315}',
        )

    @time_machine.travel("2021-02-25T15:10:00Z", tick=False)
    def test_rejects_an_expired_signature(self) -> None:
        credential = SimpleNamespace(signing_secret="whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
        assert not AccountAuditStartViewSet._valid_signature(
            credential,
            "msg_p5jXN8AQM9LWM0D4loKWxJek",
            "1614265330",
            "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
            b'{"test": 2432232314}',
        )
