from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.primary_keys import (
    needs_full_probe,
    resolve_merge_keys,
    should_probe_for_duplicates,
)


class TestResolveMergeKeys(SimpleTestCase):
    @parameterized.expand(
        [
            ("stored_wins_over_detection", ["order_id"], ["id"], ["id", "order_id"], ["order_id"]),
            ("detection_when_nothing_stored", None, ["id"], ["id"], ["id"]),
            ("id_is_the_last_resort", None, None, ["id", "name"], ["id"]),
            ("id_matched_case_insensitively", None, None, ["ID", "NAME"], ["ID"]),
            ("no_key_at_all", None, None, ["name"], None),
        ]
    )
    def test_precedence(
        self,
        _name: str,
        persisted: list[str] | None,
        detected: list[str] | None,
        columns: list[str],
        expected: list[str] | None,
    ) -> None:
        assert resolve_merge_keys(persisted, detected, columns) == expected


class TestShouldProbeForDuplicates(SimpleTestCase):
    @parameterized.expand(
        [
            ("enforced_declared_key_is_already_unique", ["id"], ["id"], True, False),
            ("unenforced_declared_key_proves_nothing", ["id"], ["id"], False, True),
            ("customer_key_is_not_a_constraint", ["email"], ["id"], True, True),
            ("id_guess_is_not_a_constraint", ["id"], None, True, True),
            ("nothing_to_probe", None, ["id"], False, False),
        ]
    )
    def test_gate(
        self,
        _name: str,
        merge_keys: list[str] | None,
        declared_keys: list[str] | None,
        constraints_enforced: bool,
        expected: bool,
    ) -> None:
        assert (
            should_probe_for_duplicates(merge_keys, declared_keys, constraints_enforced=constraints_enforced)
            is expected
        )


class TestNeedsFullProbe(SimpleTestCase):
    @parameterized.expand(
        [
            ("never_verified", ["id"], None, True),
            ("verified_the_same_key", ["id"], ["id"], False),
            ("verified_a_different_key", ["order_id"], ["id"], True),
            ("verified_a_narrower_key", ["tenant", "id"], ["id"], True),
        ]
    )
    def test_cadence(self, _name: str, merge_keys: list[str], verified: list[str] | None, expected: bool) -> None:
        assert needs_full_probe(merge_keys, verified) is expected
