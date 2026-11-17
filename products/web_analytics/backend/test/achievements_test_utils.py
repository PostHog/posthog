from collections.abc import Callable

from products.web_analytics.backend.achievements.evaluators import EVALUATORS, EvalContext


def make_evaluators(**overrides: Callable[[EvalContext], int]) -> dict[str, Callable[[EvalContext], int]]:
    evaluators: dict[str, Callable[[EvalContext], int]] = {key: (lambda ctx: 0) for key in EVALUATORS}
    evaluators.update(overrides)
    return evaluators
