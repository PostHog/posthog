import pytest
from unittest.mock import patch

from django.test import override_settings

from products.warehouse_sources.backend.temporal.data_imports.sources.common.request_pacer import RequestPacer
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point


class TestRequestPacer:
    def _pacer(self, per_second: float = 10.0) -> tuple[RequestPacer, dict[str, float], list[float]]:
        clock = {"now": 0.0}
        sleeps: list[float] = []
        return RequestPacer(per_second, clock=lambda: clock["now"], sleep=sleeps.append), clock, sleeps

    def test_spaces_request_starts_at_the_base_rate(self):
        pacer, _clock, sleeps = self._pacer()

        for _ in range(3):
            pacer.wait_turn()

        assert sleeps == pytest.approx([0.1, 0.2])

    def test_a_rate_limit_holds_for_retry_after_and_halves_the_rate(self):
        pacer, _clock, sleeps = self._pacer()
        pacer.wait_turn()

        pacer.throttled(retry_after=5)
        pacer.wait_turn()
        pacer.wait_turn()

        assert sleeps == pytest.approx([5.0, 5.2])

    def test_a_rate_limit_holds_a_worker_that_already_reserved_its_slot(self):
        clock = {"now": 0.0}
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock["now"] += seconds
            if len(sleeps) == 1:
                pacer.throttled(retry_after=5)

        pacer = RequestPacer(10.0, clock=lambda: clock["now"], sleep=sleep)
        pacer.wait_turn()
        pacer.wait_turn()

        assert sleeps == pytest.approx([0.1, 5.0])

    def test_rate_limits_reported_during_a_hold_do_not_compound(self):
        pacer, clock, sleeps = self._pacer()
        pacer.throttled(retry_after=5)
        pacer.throttled(retry_after=5)

        clock["now"] = 4.9
        pacer.wait_turn()
        pacer.wait_turn()

        assert sleeps == pytest.approx([0.1, 0.3])

    def test_the_rate_recovers_after_a_quiet_window(self):
        pacer, clock, sleeps = self._pacer()
        pacer.throttled(retry_after=None)

        clock["now"] = 31.0
        pacer.wait_turn()
        pacer.wait_turn()

        assert sleeps == pytest.approx([0.1])

    def test_a_vendor_specific_hold_replaces_the_default(self) -> None:
        # A vendor that documents no Retry-After takes the fallback on every throttle, so the hold
        # has to be the one it chose. Inheriting a default sized for a vendor that sends the header
        # would keep the pool slow for far longer than that vendor needs.
        clock = {"now": 0.0}
        sleeps: list[float] = []
        pacer = RequestPacer(10.0, clock=lambda: clock["now"], sleep=sleeps.append, hold_seconds=2.0)

        pacer.throttled(None)
        clock["now"] = 2.0
        pacer.wait_turn()
        pacer.wait_turn()

        # Recovered to the base 0.1s spacing after its own 2s window, not after the 30s default.
        assert sleeps[-1] == pytest.approx(0.1)

    def test_a_longer_retry_after_extends_a_hold_already_running(self) -> None:
        # Requests in flight when the first 429 lands all report it. A vendor naming a deadline past
        # the hold already running is not that: keeping only the first would resume early.
        clock = {"now": 0.0}
        sleeps: list[float] = []
        pacer = RequestPacer(10.0, clock=lambda: clock["now"], sleep=sleeps.append)

        pacer.throttled(5.0)
        pacer.throttled(20.0)
        clock["now"] = 6.0
        pacer.wait_turn()

        # Still held at 6s, because the second 429 moved the deadline out to 20s.
        assert sleeps[-1] == pytest.approx(14.0)

    def test_a_shorter_or_missing_retry_after_does_not_extend(self) -> None:
        clock = {"now": 0.0}
        sleeps: list[float] = []
        pacer = RequestPacer(10.0, clock=lambda: clock["now"], sleep=sleeps.append, hold_seconds=30.0)

        pacer.throttled(20.0)
        pacer.throttled(1.0)
        pacer.throttled(None)
        clock["now"] = 20.0
        pacer.wait_turn()

        # The 20s deadline stands: neither the shorter header nor the bare repeat moved it.
        assert sleeps == []

    @override_settings(DATA_WAREHOUSE_SOURCE_MAX_RETRY_AFTER_SECONDS=300.0)
    def test_a_retry_after_above_the_limit_holds_for_the_limit(self) -> None:
        pacer, clock, sleeps = self._pacer()

        pacer.throttled(100_000.0)
        pacer.throttled(200_000.0)
        pacer.wait_turn()

        assert sleeps == pytest.approx([300.0])

    @pytest.mark.parametrize("shutting_down,expected_sleep", [(False, 60.0), (True, 0.0)])
    def test_a_hold_ends_when_the_worker_shuts_down(self, shutting_down: bool, expected_sleep: float) -> None:
        pacer = RequestPacer(10.0, clock=lambda: 0.0)
        pacer.throttled(60.0)

        with (
            patch("time.sleep") as sleep,
            activate_safe_point(
                lambda: None, covers_framework_checkpoints=False, is_shutting_down=lambda: shutting_down
            ),
        ):
            pacer.wait_turn()

        assert sum(call.args[0] for call in sleep.call_args_list) == pytest.approx(expected_sleep)
