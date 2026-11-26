from collections.abc import Mapping

from django.db.models import Count, Q

from products.workflows.backend.facade.contracts import AdventCalendarQuestionResult, AdventCalendarShare
from products.workflows.backend.facade.enums import AdventCalendarDay, AdventCalendarOption
from products.workflows.backend.models.advent_calendar_answer import AdventCalendarAnswer

ADVENT_CALENDAR_QUESTIONS: Mapping[AdventCalendarDay, tuple[AdventCalendarOption, ...]] = {
    AdventCalendarDay.FAVORITE_FOUNDER: (AdventCalendarOption.JAMES, AdventCalendarOption.TIM),
    AdventCalendarDay.PINEAPPLE_ON_PIZZA: (AdventCalendarOption.YES, AdventCalendarOption.NO),
    AdventCalendarDay.TABS_OR_SPACES: (AdventCalendarOption.TABS, AdventCalendarOption.SPACES),
    AdventCalendarDay.DARK_OR_LIGHT_MODE: (AdventCalendarOption.DARK, AdventCalendarOption.LIGHT),
    AdventCalendarDay.SHIP_ON_A_FRIDAY: (AdventCalendarOption.YES, AdventCalendarOption.NO),
    AdventCalendarDay.COFFEE_OR_TEA: (AdventCalendarOption.COFFEE, AdventCalendarOption.TEA),
}


def answer_advent_calendar(
    user_id: int, day: AdventCalendarDay, option: AdventCalendarOption
) -> list[AdventCalendarQuestionResult]:
    AdventCalendarAnswer.objects.get_or_create(user_id=user_id, day=day, defaults={"option": option})
    return advent_calendar_results(user_id)


def advent_calendar_results(user_id: int) -> list[AdventCalendarQuestionResult]:
    rows = AdventCalendarAnswer.objects.values("day", "option").annotate(
        count=Count("id"), own=Count("id", filter=Q(user_id=user_id))
    )
    counts = {(row["day"], row["option"]): row["count"] for row in rows}
    own_answers = {row["day"]: AdventCalendarOption(row["option"]) for row in rows if row["own"]}
    return [
        AdventCalendarQuestionResult(
            day=day,
            answer=own_answers.get(day),
            shares=_shares({option: counts.get((day, option), 0) for option in options}),
        )
        for day, options in ADVENT_CALENDAR_QUESTIONS.items()
    ]


def _shares(counts: Mapping[AdventCalendarOption, int]) -> tuple[AdventCalendarShare, ...]:
    total = sum(counts.values())
    return tuple(
        AdventCalendarShare(option=option, share=round(count * 100 / total) if total else 0)
        for option, count in counts.items()
    )
