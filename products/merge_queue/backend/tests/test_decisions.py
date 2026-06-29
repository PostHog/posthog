import asyncio

import pytest

from parameterized import parameterized

from products.merge_queue.backend.facade.decisions import (
    DeterministicDefaults,
    Disposition,
    GatedProvider,
    PartitionSignals,
    StrategyDecision,
    TrialResult,
)
from products.merge_queue.backend.facade.types import PRRef
from products.merge_queue.backend.models import Strategy

PR = PRRef(repo="PostHog/posthog", number=1, head_sha="a" * 40)
SIGNALS = PartitionSignals(failure_rate=0.0, queue_depth=0, ci_cost_recent=0.0, enrolled_count=0)


def _defaults(*, flaky: set[str] | None = None, pinned: Strategy = Strategy.AUTO) -> DeterministicDefaults:
    flaky = flaky or set()
    return DeterministicDefaults(
        flaky=type("F", (), {"is_flaky": staticmethod(lambda repo, t: t in flaky)})(),
        pinned=lambda _partition: pinned,
    )


class _Promotion:
    def __init__(self, live: set[str]):
        self._live = live

    def is_live(self, hook: str) -> bool:
        return hook in self._live


class _Cowboy:
    """A stand-in DecisionProvider that returns a distinct strategy (or raises)."""

    def __init__(self, *, raises: bool = False):
        self._raises = raises

    async def select_strategy(self, partition, signals) -> StrategyDecision:
        if self._raises:
            raise RuntimeError("cowboy down")
        return StrategyDecision(Strategy.SPECULATIVE, 3, None, "cowboy says speculate")

    async def predict_collision(self, *a, **k): ...
    async def on_conflict(self, *a, **k): ...
    async def triage_ejection(self, *a, **k): ...


def _triage_input(failing: list[str]) -> TrialResult:
    return TrialResult(trial_id=1, pr=PR, partition="default", failing_tests=failing, attempt=1, log_ref=None)


class TestDeterministicDefaults:
    @parameterized.expand([(Strategy.AUTO, Strategy.SERIAL), (Strategy.OPTIMISTIC, Strategy.OPTIMISTIC)])
    async def test_select_strategy_resolves_auto_to_serial(self, pinned, expected):
        decision = await _defaults(pinned=pinned).select_strategy("default", SIGNALS)
        assert decision.strategy is expected

    @parameterized.expand(
        [
            ("all flaky", ["flake_a", "flake_b"], {"flake_a", "flake_b"}, Disposition.RETRY_FLAKY),
            ("one stable", ["flake_a", "real"], {"flake_a"}, Disposition.EJECT_TO_HUMAN),
            ("no failing tests", [], set(), Disposition.EJECT_TO_HUMAN),
        ]
    )
    async def test_triage_flaky_vs_stable(self, _name, failing, flaky, expected):
        decision = await _defaults(flaky=flaky).triage_ejection(_triage_input(failing))
        assert decision.disposition is expected


class TestGatedProvider:
    async def test_cowboy_none_returns_default_without_recording(self):
        recorded: list = []

        async def record(*args):
            recorded.append(args)

        gated = GatedProvider(_defaults(pinned=Strategy.OPTIMISTIC), None, _Promotion(set()), record)
        decision = await gated.select_strategy("default", SIGNALS)
        await asyncio.sleep(0)
        assert decision.strategy is Strategy.OPTIMISTIC
        assert recorded == []

    async def test_shadow_acts_on_default_and_records_would_be(self):
        done = asyncio.Event()
        recorded: list = []

        async def record(hook, args, kwargs, taken):
            recorded.append((hook, taken))
            done.set()

        gated = GatedProvider(_defaults(pinned=Strategy.OPTIMISTIC), _Cowboy(), _Promotion(set()), record)
        decision = await gated.select_strategy("default", SIGNALS)
        await asyncio.wait_for(done.wait(), 1)
        # acted on the deterministic default...
        assert decision.strategy is Strategy.OPTIMISTIC
        # ...and recorded a shadow decision for the hook
        assert recorded[0][0] == "select_strategy"

    async def test_live_calls_cowboy(self):
        async def record(*args): ...

        gated = GatedProvider(_defaults(), _Cowboy(), _Promotion({"select_strategy"}), record)
        decision = await gated.select_strategy("default", SIGNALS)
        assert decision.strategy is Strategy.SPECULATIVE

    async def test_live_falls_back_to_default_when_cowboy_raises(self):
        async def record(*args): ...

        gated = GatedProvider(
            _defaults(pinned=Strategy.OPTIMISTIC), _Cowboy(raises=True), _Promotion({"select_strategy"}), record
        )
        decision = await gated.select_strategy("default", SIGNALS)
        assert decision.strategy is Strategy.OPTIMISTIC


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
