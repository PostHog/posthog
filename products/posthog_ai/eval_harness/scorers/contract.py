"""The PostHog-owned scorer contract.

Ships as a shim today: ``Score`` re-exports braintrust's and ``Scorer`` is an
empty subclass of braintrust's base — zero behavior change. Both still satisfy
braintrust's duck-typed dispatch (``hasattr(scorer, "eval_async")``) and score
check (``name``/``score``/``metadata``/``as_dict``), so scorers written against
this module stay directly consumable by ``BraintrustEngine`` with no adapter.

A later flip replaces these with pure PostHog classes carrying the same surface
(``eval_async(output, expected, **kwargs)``, ``_name()``, ``Score.name/score/
metadata/as_dict``) — a single-file change that no scorer has to follow.
"""

from __future__ import annotations

from typing import Any

from braintrust import Score as Score
from braintrust_core.score import Scorer as _UpstreamScorer


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
