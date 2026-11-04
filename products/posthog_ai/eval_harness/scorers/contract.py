"""The PostHog-owned scorer contract.

``Score`` extends braintrust's normalized score with an optional reporting
outcome. ``Scorer`` retains braintrust's execution behavior. Both still satisfy
braintrust's duck-typed dispatch (``hasattr(scorer, "eval_async")``) and score
check (``name``/``score``/``metadata``/``as_dict``), so scorers written against
this module stay directly consumable by ``BraintrustEngine`` with no adapter.

Set ``Score.result`` for categorical values, explicit statuses, or other
reporting details. ``Score.score`` still controls the existing score averages;
use ``None`` when the reporting outcome has no numeric aggregate.
"""

from __future__ import annotations

from typing import Any

from braintrust import Score as BraintrustScore
from braintrust_core.score import Scorer as _UpstreamScorer

from posthog.dataclasses import frozen

from ..engines.types import ScorerResult


@frozen(frozen=False)
class Score(BraintrustScore):
    result: ScorerResult | None = None


class Scorer(_UpstreamScorer):
    """PostHog's scorer base. An empty subclass of braintrust's base for now."""


class AsyncOnlyScorerMixin:
    """Marks a scorer as async-only; the sync branch is unreachable in the harness.

    The harness runs every scorer through the engine, which dispatches via
    ``eval_async``, so async-only scorers turn the never-used sync branch into an
    explicit error instead of a silently divergent code path.
    """

    def _run_eval_sync(self, output: Any, expected: Any = None, **kwargs: Any) -> Score:
        raise NotImplementedError(f"{type(self).__name__} is async-only; call eval_async()")
