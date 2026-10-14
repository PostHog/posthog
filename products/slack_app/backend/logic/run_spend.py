"""The money a Slack reply reports about the run behind it."""

from decimal import Decimal

_CENTS_IN_DOLLAR = Decimal(100)


def spend_label(cents: int | None) -> str | None:
    """``cents`` as the dollar figure a reply shows, or ``None`` when there is nothing to say.

    Spend is recorded in whole cents, so a real charge below half a cent arrives here as
    zero. It renders as ``<$0.01``, because ``$0.00`` would read as free, which is the one
    thing the figure must never say by accident.
    """
    if cents is None:
        return None
    if cents <= 0:
        return "<$0.01"
    return f"${Decimal(cents) / _CENTS_IN_DOLLAR:,.2f}"


def plan_title_with_spend(title: str | None, cents: int | None) -> str | None:
    """``title`` with the turn's spend after it, such as "Done in 1m 12s · $0.42".

    The plan title is the one line a collapsed reply still shows, so the figure reaches a
    reader who never opens the plan.
    """
    label = spend_label(cents)
    if not title or label is None:
        return title
    return f"{title} · {label}"
