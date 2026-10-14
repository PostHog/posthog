from django.test import SimpleTestCase

from parameterized import parameterized

from products.slack_app.backend.logic.run_spend import plan_title_with_spend, spend_label


class TestRunSpend(SimpleTestCase):
    @parameterized.expand(
        [
            ("dollars", 267, "$2.67"),
            ("whole_dollar", 100, "$1.00"),
            # Spend is recorded in whole cents, so a real charge under half a cent arrives
            # here as zero, and rounding it to `$0.00` would report a paid turn as free.
            ("sub_cent", 0, "<$0.01"),
            ("unpriced", None, None),
        ]
    )
    def test_a_charge_never_reads_as_free(self, _name: str, cents: int | None, expected: str | None) -> None:
        assert spend_label(cents) == expected

    @parameterized.expand(
        [
            ("priced", "Done in 1m 12s", 42, "Done in 1m 12s · $0.42"),
            ("unpriced", "Done in 1m 12s", None, "Done in 1m 12s"),
            ("stopped", "Stopped", 42, "Stopped · $0.42"),
            # With no plan block the figure has nowhere to go, and must not become the title.
            ("no_plan", None, 42, None),
        ]
    )
    def test_the_spend_follows_the_duration(
        self, _name: str, title: str | None, cents: int | None, expected: str | None
    ) -> None:
        assert plan_title_with_spend(title, cents) == expected
