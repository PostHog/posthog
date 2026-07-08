from collections.abc import Callable

from products.web_analytics.backend.achievements.evaluators import EvalContext

ALL_EVALUATOR_KEYS = ["streak", "loyal_days", "data_events", "recordings_opened", "cumulative_pageviews", "conversions"]


def make_evaluators(**overrides: Callable[[EvalContext], int]) -> dict[str, Callable[[EvalContext], int]]:
    evaluators: dict[str, Callable[[EvalContext], int]] = {key: (lambda ctx: 0) for key in ALL_EVALUATOR_KEYS}
    evaluators.update(overrides)
    return evaluators
