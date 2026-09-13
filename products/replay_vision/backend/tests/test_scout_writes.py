from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import PermissionDenied, ValidationError

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.scout_writes import check_scout_scanner_credit_limit, refuse_scout_scanner_delete


class TestScoutScannerDelete(SimpleTestCase):
    def test_refuses_a_scout(self) -> None:
        with self.assertRaises(PermissionDenied):
            refuse_scout_scanner_delete(True)

    def test_allows_every_other_caller(self) -> None:
        refuse_scout_scanner_delete(False)


class TestScoutScannerCreditLimit(SimpleTestCase):
    @parameterized.expand(
        [
            ("create_with_a_limit", None, {"credit_limit": 500}, True),
            ("create_without_a_limit", None, {"name": "watcher"}, False),
            ("create_with_a_null_limit", None, {"credit_limit": None}, False),
            ("update_leaving_the_limit_alone", {"credit_limit": 500}, {"scanner_config": {"prompt": "p"}}, True),
            ("update_raising_the_limit", {"credit_limit": 500}, {"credit_limit": 900}, True),
            ("update_clearing_the_limit", {"credit_limit": 500}, {"credit_limit": None}, False),
            # A scanner someone else left uncapped is already spending, so a prompt fix on it is
            # allowed. Only widening what it can spend is not.
            ("update_of_an_uncapped_scanner", {"credit_limit": None}, {"scanner_config": {"prompt": "p"}}, True),
            ("disabling_an_uncapped_scanner", {"credit_limit": None, "enabled": True}, {"enabled": False}, True),
            ("enabling_an_uncapped_scanner", {"credit_limit": None, "enabled": False}, {"enabled": True}, False),
            (
                "enabling_an_uncapped_scanner_with_a_limit",
                {"credit_limit": None, "enabled": False},
                {"enabled": True, "credit_limit": 500},
                True,
            ),
            (
                "re_sending_enabled_on_an_uncapped_scanner",
                {"credit_limit": None, "enabled": True},
                {"enabled": True},
                True,
            ),
        ]
    )
    def test_scout_writes(
        self, _name: str, instance_fields: dict[str, Any] | None, attrs: dict[str, Any], allowed: bool
    ) -> None:
        instance = None if instance_fields is None else ReplayScanner(**instance_fields)
        if allowed:
            check_scout_scanner_credit_limit(True, instance=instance, attrs=attrs)
            return
        with self.assertRaises(ValidationError) as caught:
            check_scout_scanner_credit_limit(True, instance=instance, attrs=attrs)
        self.assertIn("credit_limit", caught.exception.detail)

    @parameterized.expand(
        [
            ("create_without_a_limit", None, {"name": "watcher"}),
            ("update_clearing_the_limit", {"credit_limit": 500}, {"credit_limit": None}),
            ("enabling_an_uncapped_scanner", {"credit_limit": None, "enabled": False}, {"enabled": True}),
        ]
    )
    def test_every_other_caller_is_untouched(
        self, _name: str, instance_fields: dict[str, Any] | None, attrs: dict[str, Any]
    ) -> None:
        instance = None if instance_fields is None else ReplayScanner(**instance_fields)
        check_scout_scanner_credit_limit(False, instance=instance, attrs=attrs)
