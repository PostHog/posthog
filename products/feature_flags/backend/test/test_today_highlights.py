from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend import today_highlights
from products.feature_flags.backend.facade.today_highlights import HIGHLIGHT_SOURCES
from products.feature_flags.backend.facade.usage import CreatedFlag, FlagCalls, FlagCallSummary
from products.today.backend.facade.contracts import HighlightContext

MONDAY = date(2026, 10, 12)
TUESDAY = date(2026, 10, 13)


def created(
    key: str, days_old: int, *, flag_id: int = 1, blocked: bool = False, remote_configuration: bool = False
) -> CreatedFlag:
    return CreatedFlag(
        id=flag_id,
        key=key,
        created_at=datetime(2026, 10, 12, 9, tzinfo=UTC) - timedelta(days=days_old),
        removal_blocked=blocked,
        remote_configuration=remote_configuration,
    )


def calls(people: int = 0, people_before: int = 0, calls_this_week: int = 0, values: int = 0) -> FlagCalls:
    return FlagCalls(
        people_this_week=people,
        people_last_week=people_before,
        calls_this_week=calls_this_week,
        calls=calls_this_week + people_before,
        values_this_week=values,
        value_this_week="true" if values else None,
    )


SAME = calls(people=50, calls_this_week=200_000, values=1)


class TestFlags(SimpleTestCase):
    def _find(
        self,
        today: date,
        created_flags: list[CreatedFlag],
        by_key: dict[str, FlagCalls],
        *,
        complete: bool = True,
        covers_all_environments: bool = True,
    ) -> list[tuple[str, str, str | None]]:
        context = cast(
            HighlightContext,
            SimpleNamespace(
                team=SimpleNamespace(id=1, timezone_info=ZoneInfo("UTC")),
                user=SimpleNamespace(id=2),
                today=today,
                daily=lambda _name, compute: compute(),
            ),
        )
        registered = next(s for s in HIGHLIGHT_SOURCES if s.name == "flags")
        summary = FlagCallSummary(by_key=by_key, complete=complete, covers_all_environments=covers_all_environments)
        with (
            patch.object(today_highlights, "list_flags_created_by", return_value=created_flags),
            patch.object(today_highlights, "summarize_flag_calls", return_value=summary),
        ):
            return [(c.title, c.detail, c.url) for c in registered.find(context).items]

    def test_a_flag_that_reaches_half_the_people_is_a_risk_even_when_removal_is_blocked(self) -> None:
        found = self._find(TUESDAY, [created("checkout", 60, flag_id=7, blocked=True)], {"checkout": calls(10, 40)})

        self.assertEqual(
            found,
            [
                (
                    "Flag ‘checkout’ reached 75% fewer users in the last 7 days",
                    "40 → 10 · Check the code that calls it",
                    "/feature_flags/7",
                )
            ],
        )

    @parameterized.expand(
        [
            ("unused", created("old-banner", 30), {}, {}, "Flag ‘old-banner’ had no evaluations in the last 14 days"),
            (
                "same value",
                created("old-banner", 30),
                {"old-banner": SAME},
                {},
                "Flag ‘old-banner’ is true for everyone",
            ),
            ("unused but the call list is cut", created("old-banner", 30), {}, {"complete": False}, None),
            (
                "unused in one of several environments",
                created("old-banner", 30),
                {},
                {"covers_all_environments": False},
                None,
            ),
            (
                "same value in one of several environments",
                created("old-banner", 30),
                {"old-banner": SAME},
                {"covers_all_environments": False},
                None,
            ),
            ("too new", created("old-banner", 13), {}, {}, None),
            ("blocked by an experiment or a reference", created("old-banner", 30, blocked=True), {}, {}, None),
            ("a remote configuration", created("old-banner", 30, remote_configuration=True), {}, {}, None),
            ("risky to remove", created("kill-switch", 30), {}, {}, None),
            ("a survey flag", created("survey-targeting-abc", 30), {}, {}, None),
        ]
    )
    def test_monday_cleanup_names_an_unused_or_same_value_flag(
        self,
        _name: str,
        flag: CreatedFlag,
        by_key: dict[str, FlagCalls],
        evidence: dict[str, bool],
        title: str | None,
    ) -> None:
        found = self._find(MONDAY, [flag], by_key, **evidence)

        self.assertEqual([t for t, _, _ in found], [title] if title else [])

    @parameterized.expand(
        [
            ("monday list", MONDAY, 4, "flag_0, flag_1, flag_2 and 1 more"),
            ("costly list", TUESDAY, 4, "Same value for everyone: flag_0, flag_1, flag_2 and 1 more"),
        ]
    )
    def test_cleanup_detail_names_the_first_flags(self, _name: str, today: date, count: int, expected: str) -> None:
        created_flags = [created(f"flag_{i}", 100 - i, flag_id=i) for i in range(count)]

        found = self._find(today, created_flags, {flag.key: SAME for flag in created_flags})

        self.assertEqual([d for _, d, _ in found], [expected])

    def test_same_value_flags_called_less_than_the_cost_floor_stay_hidden_outside_monday(self) -> None:
        cheap = calls(people=50, calls_this_week=99_999, values=1)

        self.assertEqual(self._find(TUESDAY, [created("old-banner", 60)], {"old-banner": cheap}), [])
