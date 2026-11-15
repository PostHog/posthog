from collections.abc import Callable

from products.web_analytics.backend.achievements.evaluators import EvalContext, PriorProgress, TrackEvaluation

ALL_EVALUATOR_KEYS = ["streak", "loyal_days", "data_events", "recordings_opened"]
ALL_INCREMENTAL_EVALUATOR_KEYS = ["cumulative_pageviews", "conversions"]

IncrementalEvaluator = Callable[[EvalContext, PriorProgress], TrackEvaluation]


def make_evaluators(**overrides: Callable[[EvalContext], int]) -> dict[str, Callable[[EvalContext], int]]:
    evaluators: dict[str, Callable[[EvalContext], int]] = {key: (lambda ctx: 0) for key in ALL_EVALUATOR_KEYS}
    evaluators.update(overrides)
    return evaluators


def _returning(value: int) -> IncrementalEvaluator:
    def evaluate(_ctx: EvalContext, _prior: PriorProgress) -> TrackEvaluation:
        return TrackEvaluation(value=value, checkpoint={})

    return evaluate


def make_incremental_evaluators(**values: int) -> dict[str, IncrementalEvaluator]:
    return {key: _returning(values.get(key, 0)) for key in ALL_INCREMENTAL_EVALUATOR_KEYS}
