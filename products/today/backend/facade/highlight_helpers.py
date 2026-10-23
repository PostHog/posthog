"""Shared helpers for highlight sources: number and text formatting, product use, routines, and trend detection."""

from ..logic.highlight_rules import exact, human, short, users, uses_product
from ..logic.highlight_trends import BAD_METRIC, MONEY, UNCLEAR_LABEL, UNKNOWN_DIRECTION, complete, detect, stale
from ..logic.routines import routine_days_for, viewed_days

__all__ = [
    "BAD_METRIC",
    "MONEY",
    "UNCLEAR_LABEL",
    "UNKNOWN_DIRECTION",
    "complete",
    "detect",
    "exact",
    "human",
    "routine_days_for",
    "short",
    "stale",
    "users",
    "uses_product",
    "viewed_days",
]
