from datetime import UTC, datetime, timedelta

from django.test import SimpleTestCase

from parameterized import parameterized

from products.release.backend.facade.contracts import ImportFlag
from products.release.backend.logic.imports import group_import_candidates

START = datetime(2026, 1, 1, tzinfo=UTC)


def flag(flag_id: int, key: str, days: int = 0, creator: int | None = 1) -> ImportFlag:
    return ImportFlag(
        id=flag_id,
        key=key,
        created_at=START + timedelta(days=days),
        created_by_id=creator,
    )


class TestGroupImportCandidates(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "groups flags by prefix and creator inside the window",
                [flag(1, "checkout-v2"), flag(2, "checkout-banner", days=3)],
                [("related_flags", "Checkout", [1, 2])],
            ),
            (
                "names a group by the shared key prefix",
                [flag(1, "billing-page-header"), flag(2, "billing-page-footer", days=1)],
                [("related_flags", "Billing page", [1, 2])],
            ),
            (
                "splits a prefix group across a gap longer than the window",
                [flag(1, "checkout-v2"), flag(2, "checkout-banner", days=30)],
                [("flag", "Checkout banner", [2]), ("flag", "Checkout v2", [1])],
            ),
            (
                "measures the window from the first flag of a group",
                [flag(1, "checkout-v2"), flag(2, "checkout-banner", days=10), flag(3, "checkout-autofill", days=20)],
                [("flag", "Checkout autofill", [3]), ("related_flags", "Checkout", [1, 2])],
            ),
            (
                "keeps flags of different creators apart",
                [flag(1, "checkout-v2"), flag(2, "checkout-banner", creator=2)],
                [("flag", "Checkout v2", [1]), ("flag", "Checkout banner", [2])],
            ),
        ]
    )
    def test_grouping(self, _name: str, flags: list[ImportFlag], expected: list) -> None:
        candidates = group_import_candidates(flags, linked=set())

        assert [(item.reason.value, item.name, item.feature_flag_ids) for item in candidates] == expected

    def test_skips_linked_flags(self) -> None:
        candidates = group_import_candidates([flag(1, "checkout-v2"), flag(2, "checkout-banner")], linked={1})

        assert [item.feature_flag_ids for item in candidates] == [[2]]

    def test_splits_large_groups_at_the_link_limit(self) -> None:
        flags = [flag(index, f"checkout-step-{index}") for index in range(1, 151)]

        candidates = group_import_candidates(flags, linked=set())

        assert sorted(len(item.feature_flag_ids) for item in candidates) == [50, 100]
