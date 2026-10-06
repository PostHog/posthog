from datetime import datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.logic.impact import impact_numbers, last_occurrence
from products.today.backend.logic.signal_text import SignalInput
from products.today.backend.tests.factories import signal


def ticket(number: int, timestamp: str, product: str = "conversations") -> SignalInput:
    return signal(
        source_product=product,
        source_type="ticket",
        source_id=f"ticket-{number}",
        timestamp=timestamp,
        extra={"ticket_number": number},
    )


def slow_query(content: str) -> SignalInput:
    return signal(source_product="pganalyze", source_type="issue", content=content)


class TestImpact(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "counts distinct support tickets over the days they span",
                [ticket(1042, "2026-09-20T09:00:00+00:00"), ticket(1043, "2026-09-25T15:00:00+00:00")],
                [("2", "support tickets over 6 days.")],
            ),
            (
                "counts tickets from any support tool, and the same number in two tools twice",
                [ticket(1042, "2026-09-20T09:00:00+00:00", "freshdesk"), ticket(1042, "2026-09-21T09:00:00+00:00")],
                [("2", "support tickets over 2 days.")],
            ),
            (
                "shows nothing for one ticket, however many signals cite it",
                [ticket(1042, "2026-09-20T09:00:00+00:00"), ticket(1042, "2026-09-25T15:00:00+00:00")],
                [],
            ),
            (
                "works out the database time a slow query costs each day",
                [slow_query("[info] orders-db — #42\nQuery #42 takes 120 ms on average (30,000 calls in last 24h)")],
                [("1 hour", "database time a day, worked out from the query’s pganalyze stats.")],
            ),
            (
                "rounds a fraction of an hour up at the half",
                [slow_query("Query #7 takes 2.25 ms on average (4,000,000 calls in last 24h)")],
                [("2.5 hours", "database time a day, worked out from the query’s pganalyze stats.")],
            ),
        ]
    )
    def test_sizes_impact(self, _name: str, signals: list[SignalInput], expected: list[tuple[str, str]]) -> None:
        assert [(number.value, number.sentence) for number in impact_numbers(signals)] == expected

    @parameterized.expand(
        [
            (
                "the newest session, ticket or alert, not a later finding",
                [
                    signal(
                        source_product="replay_vision",
                        timestamp="2026-09-20T10:00:00+00:00",
                        extra={"session_id": "s1"},
                    ),
                    ticket(1042, "2026-09-25T08:00:00+00:00"),
                    signal(timestamp="2026-09-30T10:00:00+00:00"),
                ],
                "2026-09-25T08:00:00+00:00",
            ),
            (
                "a later signal about the same session",
                [
                    signal(source_product="replay_vision", timestamp=at, extra={"session_id": "s1"})
                    for at in ("2026-09-20T10:00:00+00:00", "2026-09-27T10:00:00+00:00")
                ],
                "2026-09-27T10:00:00+00:00",
            ),
            ("nothing when no signal is an occurrence", [signal()], None),
        ]
    )
    def test_dates_the_last_occurrence_as(self, _name: str, signals: list[SignalInput], expected: str | None) -> None:
        assert last_occurrence(signals) == (datetime.fromisoformat(expected) if expected else None)
