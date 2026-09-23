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
            (
                "change_query_without_a_limit",
                {"credit_limit": None, "query": {"kind": "RecordingsQuery"}},
                {"query": {}},
                False,
            ),
            (
                "change_sampling_without_a_limit",
                {"credit_limit": None, "sampling_rate": 0.1},
                {"sampling_rate": 1.0},
                False,
            ),
            (
                "change_sampling_mode_without_a_limit",
                {"credit_limit": None, "sampling_mode": "focused"},
                {"sampling_mode": "comprehensive"},
                False,
            ),
            ("change_model_without_a_limit", {"credit_limit": None, "model": "old"}, {"model": "new"}, False),
            (
                "clear_targeting_without_a_limit",
                {"credit_limit": None, "experiment_targeting": {"experiment_id": 1}},
                {"experiment_targeting": None},
                False,
            ),
            (
                "change_with_a_limit",
                {"credit_limit": None, "sampling_rate": 0.1},
                {"sampling_rate": 1.0, "credit_limit": 500},
                True,
            ),
            ("unchanged_cost_field", {"credit_limit": None, "sampling_rate": 0.1}, {"sampling_rate": 0.1}, True),
            (
                "enable_signals_without_a_limit",
                {"credit_limit": None, "enabled": True, "emits_signals": False},
                {"emits_signals": True},
                True,
            ),
            (
                "disable_signals_without_a_limit",
                {"credit_limit": None, "enabled": True, "emits_signals": True},
                {"emits_signals": False},
                True,
            ),
            (
                "disable_and_change",
                {"credit_limit": None, "sampling_rate": 0.1},
                {"sampling_rate": 1.0, "enabled": False},
                True,
            ),
            (
                "change_disabled_scanner",
                {"credit_limit": None, "enabled": False, "sampling_rate": 0.1},
                {"sampling_rate": 1.0},
                True,
            ),
            ("create_with_a_limit", None, {"credit_limit": 500}, True),
            ("create_above_the_quota", None, {"credit_limit": 2147483647}, False),
            ("create_without_an_org_quota", None, {"credit_limit": 500}, False, None),
            ("create_at_the_org_quota", None, {"credit_limit": 1000}, True),
            ("raise_above_the_quota", {"credit_limit": 500}, {"credit_limit": 1001}, False),
            ("raise_without_an_org_quota", {"credit_limit": 500}, {"credit_limit": 900}, False, None),
            ("reduce_without_an_org_quota", {"credit_limit": 500}, {"credit_limit": 250}, True, None),
            ("disable_without_an_org_quota", {"credit_limit": 500}, {"enabled": False}, True, None),
            (
                "enable_without_an_org_quota",
                {"credit_limit": 500, "enabled": False},
                {"enabled": True},
                False,
                None,
            ),
            (
                "change_sampling_without_an_org_quota",
                {"credit_limit": 500, "sampling_rate": 0.1},
                {"sampling_rate": 1.0},
                False,
                None,
            ),
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
        self,
        _name: str,
        instance_fields: dict[str, Any] | None,
        attrs: dict[str, Any],
        allowed: bool,
        max_credit_limit: int | None = 1000,
    ) -> None:
        instance = None if instance_fields is None else ReplayScanner(**instance_fields)
        if allowed:
            check_scout_scanner_credit_limit(True, instance=instance, attrs=attrs, max_credit_limit=max_credit_limit)
            return
        with self.assertRaises(ValidationError) as caught:
            check_scout_scanner_credit_limit(True, instance=instance, attrs=attrs, max_credit_limit=max_credit_limit)
        self.assertIn("credit_limit", caught.exception.detail)

    @parameterized.expand(
        [
            ("change_without_a_limit", {"credit_limit": None, "sampling_rate": 0.1}, {"sampling_rate": 1.0}),
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
