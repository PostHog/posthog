"""Decision hooks — the Stampede ↔ Cowboy seam.

The engine calls a `DecisionProvider` at each branch point. Hooks are async (Cowboy
runs sandboxes). Each has a deterministic default; `GatedProvider` composes the default
with Cowboy under the per-decision shadow/live gate. With `cowboy=None` the
engine is fully deterministic — the safety floor.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from products.merge_queue.backend.facade.types import PRRef
from products.merge_queue.backend.models import Strategy

logger = logging.getLogger(__name__)


# ---- decision inputs/outputs ----
@dataclass(frozen=True)
class PartitionSignals:  # live signals for strategy selection (read from engineering_analytics)
    failure_rate: float
    queue_depth: int
    ci_cost_recent: float
    enrolled_count: int


@dataclass(frozen=True)
class StrategyDecision:
    strategy: Strategy
    speculation_depth: int | None
    max_batch_size: int | None
    reason: str


class CollisionBasis(StrEnum):
    NONE = "none"
    STATIC = "static"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class CollisionDecision:
    collides: bool
    confidence: float
    with_prs: list[PRRef]
    basis: CollisionBasis
    reason: str


class ConflictAction(StrEnum):
    AUTO_REBASE = "auto_rebase"
    EJECT = "eject"


@dataclass(frozen=True)
class ConflictDecision:
    action: ConflictAction
    reason: str


@dataclass(frozen=True)
class TrialResult:  # input to triage
    trial_id: UUID
    pr: PRRef
    partition: str
    failing_tests: list[str]
    attempt: int
    log_ref: str | None


class Disposition(StrEnum):
    RETRY_FLAKY = "retry_flaky"
    FAST_FIX = "fast_fix"
    DISPATCH_AGENT = "dispatch_agent"
    EJECT_TO_HUMAN = "eject_to_human"


@dataclass(frozen=True)
class TriageDecision:
    disposition: Disposition
    fix_plan: dict | None  # for FAST_FIX
    brief: str | None  # for DISPATCH_AGENT
    reason: str


# ---- the provider protocol (Cowboy implements this) ----
class DecisionProvider(Protocol):
    async def select_strategy(self, partition: str, signals: PartitionSignals) -> StrategyDecision: ...
    async def predict_collision(self, pr: PRRef, projected: list[PRRef]) -> CollisionDecision: ...
    async def on_conflict(self, pr: PRRef, target_sha: str) -> ConflictDecision: ...
    async def triage_ejection(self, trial: TrialResult) -> TriageDecision: ...


class FlakyOracle(Protocol):
    def is_flaky(self, repo: str, test_id: str) -> bool: ...  # backed by the engineering_analytics flaky signal


class DeterministicDefaults:
    """The engine's behavior with Cowboy off — the baseline the shadow harness scores against."""

    def __init__(self, flaky: FlakyOracle, pinned: Callable[[str], Strategy]) -> None:
        self._flaky = flaky
        self._pinned = pinned

    async def select_strategy(self, partition: str, signals: PartitionSignals) -> StrategyDecision:
        s = self._pinned(partition)
        return StrategyDecision(
            strategy=Strategy.SERIAL if s is Strategy.AUTO else s,  # auto → serial
            speculation_depth=None,
            max_batch_size=None,
            reason="pinned/default",
        )

    async def predict_collision(self, pr: PRRef, projected: list[PRRef]) -> CollisionDecision:
        return CollisionDecision(False, 0.0, [], CollisionBasis.NONE, "let the trial decide")

    async def on_conflict(self, pr: PRRef, target_sha: str) -> ConflictDecision:
        return ConflictDecision(ConflictAction.EJECT, "default: eject to author")

    async def triage_ejection(self, trial: TrialResult) -> TriageDecision:
        if trial.failing_tests and all(self._flaky.is_flaky(trial.pr.repo, t) for t in trial.failing_tests):
            return TriageDecision(Disposition.RETRY_FLAKY, None, None, "all failing tests flagged flaky")
        return TriageDecision(Disposition.EJECT_TO_HUMAN, None, None, "non-flaky failure")


class PromotionState(Protocol):
    def is_live(self, hook: str) -> bool: ...  # backed by Cowboy's promotion.py


class GatedProvider:
    """Per-decision shadow/live composition; where shadow recording happens."""

    def __init__(
        self,
        default: DecisionProvider,
        cowboy: DecisionProvider | None,
        promotion: PromotionState,
        record_shadow: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        self._default = default
        self._cowboy = cowboy
        self._promotion = promotion
        self._record = record_shadow
        # hold live references to fire-and-forget shadow-record tasks so the GC can't drop
        # them mid-flight (see https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task)
        self._shadow_tasks: set[asyncio.Task[None]] = set()

    async def _gate(self, hook: str, args: tuple, kwargs: dict) -> Any:  # genuinely polymorphic dispatch
        default_fn = getattr(self._default, hook)
        if self._cowboy and self._promotion.is_live(hook):
            try:
                return await getattr(self._cowboy, hook)(*args, **kwargs)
            except Exception:
                logger.exception("cowboy %s failed; falling back to default", hook)
                return await default_fn(*args, **kwargs)
        taken = await default_fn(*args, **kwargs)
        if self._cowboy:  # SHADOW: act on default, record cowboy's would-be call
            task = asyncio.create_task(self._record(hook, args, kwargs, taken))  # writes a SHADOW_DECISION QueueEvent
            self._shadow_tasks.add(task)
            task.add_done_callback(self._shadow_tasks.discard)
        return taken

    async def select_strategy(self, partition: str, signals: PartitionSignals) -> StrategyDecision:
        return await self._gate("select_strategy", (partition, signals), {})

    async def predict_collision(self, pr: PRRef, projected: list[PRRef]) -> CollisionDecision:
        return await self._gate("predict_collision", (pr, projected), {})

    async def on_conflict(self, pr: PRRef, target_sha: str) -> ConflictDecision:
        return await self._gate("on_conflict", (pr, target_sha), {})

    async def triage_ejection(self, trial: TrialResult) -> TriageDecision:
        return await self._gate("triage_ejection", (trial,), {})
