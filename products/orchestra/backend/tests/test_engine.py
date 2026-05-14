import uuid

import pytest

from products.orchestra.backend.engine.context import ExecutionContext
from products.orchestra.backend.engine.db import _build_retry_seed
from products.orchestra.backend.engine.registry import _EXECUTIONS, _STEPS, execution, get_execution, get_step, step
from products.orchestra.backend.engine.replay import ReplayState, build_replay_state
from products.orchestra.backend.engine.types import Event, EventType, ScheduleStep, ScheduleTimer, StepFailed, _Suspend


class TestReplayState:
    def test_empty_history(self):
        state = build_replay_state([])
        assert state.step_results == {}
        assert state.step_errors == {}
        assert state.timer_fired == set()
        assert state.is_done is False

    def test_step_completed(self):
        history = [
            Event(
                execution_id="e1",
                run_id=uuid.uuid4(),
                event_id=0,
                event_type=EventType.STEP_SCHEDULED,
                timestamp=None,
                attributes={"step_id": 0, "step_type": "greet"},
            ),
            Event(
                execution_id="e1",
                run_id=uuid.uuid4(),
                event_id=1,
                event_type=EventType.STEP_COMPLETED,
                timestamp=None,
                attributes={"step_id": 0, "result": "Hello!"},
            ),
        ]
        state = build_replay_state(history)
        assert state.step_results == {0: "Hello!"}
        assert state.is_done is False

    def test_execution_completed(self):
        history = [
            Event(
                execution_id="e1",
                run_id=uuid.uuid4(),
                event_id=0,
                event_type=EventType.EXECUTION_COMPLETED,
                timestamp=None,
                attributes={"result": "done"},
            ),
        ]
        state = build_replay_state(history)
        assert state.is_done is True
        assert state.final_result == "done"

    def test_timer_fired(self):
        history = [
            Event(
                execution_id="e1",
                run_id=uuid.uuid4(),
                event_id=0,
                event_type=EventType.TIMER_FIRED,
                timestamp=None,
                attributes={"timer_id": 0},
            ),
        ]
        state = build_replay_state(history)
        assert 0 in state.timer_fired


class TestExecutionContext:
    @pytest.mark.anyio
    async def test_step_suspends_on_first_call(self):
        state = ReplayState()
        ctx = ExecutionContext(execution_id="e1", run_id=uuid.uuid4(), state=state)

        @step(name="test_step_ctx")
        async def my_step(input):
            return input

        with pytest.raises(_Suspend):
            await ctx.step(my_step, "hello")

        assert len(ctx.commands) == 1
        assert isinstance(ctx.commands[0], ScheduleStep)
        assert ctx.commands[0].step_type == "test_step_ctx"

        _STEPS.pop("test_step_ctx", None)

    @pytest.mark.anyio
    async def test_step_replays_cached_result(self):
        state = ReplayState(step_results={0: "cached"})
        ctx = ExecutionContext(execution_id="e1", run_id=uuid.uuid4(), state=state)

        @step(name="test_step_replay")
        async def my_step(input):
            return input

        result = await ctx.step(my_step, "hello")
        assert result == "cached"
        assert len(ctx.commands) == 0

        _STEPS.pop("test_step_replay", None)

    @pytest.mark.anyio
    async def test_step_raises_on_cached_error(self):
        state = ReplayState(step_errors={0: {"message": "boom"}})
        ctx = ExecutionContext(execution_id="e1", run_id=uuid.uuid4(), state=state)

        @step(name="test_step_error")
        async def my_step(input):
            return input

        with pytest.raises(StepFailed):
            await ctx.step(my_step, "hello")

        _STEPS.pop("test_step_error", None)

    @pytest.mark.anyio
    async def test_sleep_suspends(self):
        state = ReplayState()
        ctx = ExecutionContext(execution_id="e1", run_id=uuid.uuid4(), state=state)

        with pytest.raises(_Suspend):
            await ctx.sleep(5)

        assert len(ctx.commands) == 1
        assert isinstance(ctx.commands[0], ScheduleTimer)
        assert ctx.commands[0].seconds == 5.0

    @pytest.mark.anyio
    async def test_sleep_replays_when_fired(self):
        state = ReplayState(timer_fired={0})
        ctx = ExecutionContext(execution_id="e1", run_id=uuid.uuid4(), state=state)

        await ctx.sleep(5)
        assert len(ctx.commands) == 0


class TestBuildRetrySeed:
    def _event(self, event_type, attributes, event_id=0, run_id=None):
        return Event(
            execution_id="e1",
            run_id=run_id or uuid.uuid4(),
            event_id=event_id,
            event_type=event_type,
            timestamp=None,
            attributes=attributes,
        )

    def test_keeps_completed_step_pairs_drops_failed_pair(self):
        source_run_id = uuid.uuid4()
        history = [
            self._event(EventType.EXECUTION_STARTED, {"execution_type": "demo", "input": {"name": "Andy"}}, 0, source_run_id),
            self._event(EventType.STEP_SCHEDULED, {"step_id": 0, "step_type": "build_greeting", "input": "Andy"}, 1, source_run_id),
            self._event(EventType.STEP_COMPLETED, {"step_id": 0, "result": "Hello, Andy!"}, 2, source_run_id),
            self._event(EventType.STEP_SCHEDULED, {"step_id": 1, "step_type": "flaky_log_greeting", "input": "Hello, Andy!"}, 3, source_run_id),
            self._event(EventType.STEP_FAILED, {"step_id": 1, "error": {"type": "ValueError", "message": "boom"}}, 4, source_run_id),
            self._event(EventType.EXECUTION_FAILED, {"error": {"type": "StepFailed"}}, 5, source_run_id),
        ]

        seed = _build_retry_seed(history, source_run_id)

        kept_types = [t for t, _ in seed]
        assert kept_types == [
            EventType.EXECUTION_STARTED,
            EventType.STEP_SCHEDULED,
            EventType.STEP_COMPLETED,
        ]
        for _, attrs in seed:
            assert attrs["carried_over_from_run_id"] == str(source_run_id)

    def test_keeps_fired_timer_pairs_drops_unfired_timers(self):
        source_run_id = uuid.uuid4()
        history = [
            self._event(EventType.EXECUTION_STARTED, {"execution_type": "demo", "input": None}, 0, source_run_id),
            self._event(EventType.TIMER_SCHEDULED, {"timer_id": 0, "seconds": 2.0}, 1, source_run_id),
            self._event(EventType.TIMER_FIRED, {"timer_id": 0}, 2, source_run_id),
            self._event(EventType.TIMER_SCHEDULED, {"timer_id": 1, "seconds": 99.0}, 3, source_run_id),
            self._event(EventType.EXECUTION_FAILED, {"error": {}}, 4, source_run_id),
        ]

        seed = _build_retry_seed(history, source_run_id)
        kept_types = [t for t, _ in seed]
        assert kept_types == [
            EventType.EXECUTION_STARTED,
            EventType.TIMER_SCHEDULED,
            EventType.TIMER_FIRED,
        ]
        timer_scheduled_attrs = [a for t, a in seed if t == EventType.TIMER_SCHEDULED]
        assert timer_scheduled_attrs[0]["timer_id"] == 0

    def test_seed_replays_correctly(self):
        """The seeded history should drive replay state such that completed steps short-circuit."""
        source_run_id = uuid.uuid4()
        history = [
            self._event(EventType.EXECUTION_STARTED, {"execution_type": "demo", "input": "x"}, 0, source_run_id),
            self._event(EventType.STEP_SCHEDULED, {"step_id": 0, "step_type": "s0"}, 1, source_run_id),
            self._event(EventType.STEP_COMPLETED, {"step_id": 0, "result": "carried"}, 2, source_run_id),
            self._event(EventType.STEP_SCHEDULED, {"step_id": 1, "step_type": "s1"}, 3, source_run_id),
            self._event(EventType.STEP_FAILED, {"step_id": 1, "error": {}}, 4, source_run_id),
            self._event(EventType.EXECUTION_FAILED, {"error": {}}, 5, source_run_id),
        ]
        seed = _build_retry_seed(history, source_run_id)

        new_run_id = uuid.uuid4()
        replayed = [
            Event(
                execution_id="e1",
                run_id=new_run_id,
                event_id=i,
                event_type=t,
                timestamp=None,
                attributes=a,
            )
            for i, (t, a) in enumerate(seed)
        ]
        state = build_replay_state(replayed)
        assert state.step_results == {0: "carried"}
        assert state.step_errors == {}
        assert state.is_done is False


class TestRegistry:
    def test_register_and_lookup_execution(self):
        @execution(name="test_exec_registry")
        async def my_exec(ctx, input):
            pass

        assert get_execution("test_exec_registry") is my_exec
        _EXECUTIONS.pop("test_exec_registry", None)

    def test_register_and_lookup_step(self):
        @step(name="test_step_registry")
        async def my_step(input):
            pass

        assert get_step("test_step_registry") is my_step
        _STEPS.pop("test_step_registry", None)

    def test_lookup_missing_execution_raises(self):
        with pytest.raises(LookupError):
            get_execution("nonexistent")

    def test_lookup_missing_step_raises(self):
        with pytest.raises(LookupError):
            get_step("nonexistent")
