import datetime as dt
import dataclasses
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

import httpx
from google.genai.errors import APIError
from pydantic import BaseModel
from temporalio.testing import ActivityEnvironment

from posthog.dataclasses import frozen

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.activities.call_scanner_provider import (
    _maybe_create_video_cache,
    _MissionOutcome,
    _remaining_verify_budget_seconds,
    _run_mission,
    _run_mission_attempts,
    _run_pass,
    _run_steps,
    _step_config,
)
from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError
from products.replay_vision.backend.temporal.metrics import REPLAY_VISION_VERIFICATION_OUTCOMES
from products.replay_vision.backend.temporal.scanners.base import MissionStep
from products.replay_vision.backend.temporal.scanners.monitor import MonitorLlmResponse, MonitorOutput, MonitorScanner
from products.replay_vision.backend.temporal.types import ScannerSnapshot, VerificationRecord

_LABELS = {"provider": "gemini", "model": "gemini-3-flash-preview", "scanner_type": "monitor"}
# The driver treats the video part opaquely (just appended to the conversation), so a sentinel is fine.
_VIDEO: Any = "VIDEO"


class _Core(BaseModel):
    verdict: str


class _Side(BaseModel):
    note: str


class _FakeContent:
    def __init__(self, function_call: Any = None) -> None:
        part = type("Part", (), {"function_call": function_call})()
        self.parts = [part]


class _Resp:
    """Minimal genai response: `.text` and `.candidates[0].content.parts`."""

    def __init__(self, text: str = "", function_call: Any = None) -> None:
        self.candidates = [type("Cand", (), {"content": _FakeContent(function_call)})()]
        self.text = text


class _FakeModels:
    def __init__(self, responses: list[_Resp]) -> None:
        self._it = iter(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> _Resp:
        # Snapshot `contents` — the driver mutates the same list across turns, so a live reference would
        # show every call the final length.
        self.calls.append({**kwargs, "contents": list(kwargs["contents"])})
        return next(self._it)


class _FakeClient:
    def __init__(self, responses: list[_Resp]) -> None:
        self.models = _FakeModels(responses)


def _fc(name: str, args: dict[str, Any]) -> Any:
    return type("FC", (), {"name": name, "args": args})()


async def _run(client: _FakeClient, steps: list[MissionStep], dispatch: Any = lambda c: {}, cache_name=None):
    return await _run_steps(
        client=client,
        model="models/gemini-3-flash-preview",
        steps=steps,
        video_part=_VIDEO,
        preamble_text="PRE",
        cache_name=cache_name,
        dispatch=dispatch,
        team_id=1,
        metric_labels=_LABELS,
        trace_id="trace-1",
    )


@pytest.mark.asyncio
async def test_scanner_generations_include_team_attribution() -> None:
    scanner = MagicMock()
    scanner.mission_steps.return_value = []
    scanner.assemble.return_value = (MagicMock(), [])
    snapshot = MagicMock()
    snapshot.scanner_type.value = "monitor"
    snapshot.model = "gemini-3-flash-preview"
    snapshot.provider = "gemini"

    with (
        patch(
            "products.replay_vision.backend.temporal.activities.call_scanner_provider.genai.AsyncClient"
        ) as client_cls,
        patch("products.replay_vision.backend.temporal.activities.call_scanner_provider.GoogleGenAIClient"),
        patch(
            "products.replay_vision.backend.temporal.activities.call_scanner_provider._maybe_create_video_cache",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "products.replay_vision.backend.temporal.activities.call_scanner_provider._run_mission_attempts",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "products.replay_vision.backend.temporal.activities.call_scanner_provider.build_events_index",
            return_value={},
        ),
    ):
        await _run_mission(
            scanner=scanner,
            snapshot=snapshot,
            video_part=_VIDEO,
            preamble_text="PRE",
            team_id=42,
            llm_inputs=MagicMock(),
            trace_id="trace-1",
        )

    assert client_cls.call_args.kwargs["posthog_properties"] == {
        "ai_product": "replay_vision",
        "feature": "scanner",
        "scanner_type": "monitor",
        "team_id": 42,
    }


@pytest.mark.asyncio
async def test_runs_each_step_and_keys_outputs_by_name() -> None:
    steps = [
        MissionStep(name="core", instruction="do core", response_model=_Core),
        MissionStep(name="side", instruction="do side", response_model=_Side, required=False),
    ]
    client = _FakeClient([_Resp(text='{"verdict":"yes"}'), _Resp(text='{"note":"ok"}')])
    out = await _run(client, steps)
    assert out["core"].verdict == "yes"
    assert out["side"].note == "ok"
    assert len(client.models.calls) == 2  # one generate per step


@pytest.mark.asyncio
async def test_later_step_sees_the_earlier_answer() -> None:
    steps = [
        MissionStep(name="core", instruction="do core", response_model=_Core),
        MissionStep(name="side", instruction="do side", response_model=_Side, required=False),
    ]
    client = _FakeClient([_Resp(text='{"verdict":"yes"}'), _Resp(text='{"note":"ok"}')])
    await _run(client, steps)
    # 1st turn: [video, preamble, core instruction]; 2nd: + core answer + side instruction.
    assert len(client.models.calls[0]["contents"]) == 3
    assert len(client.models.calls[1]["contents"]) == 5


@pytest.mark.asyncio
async def test_step_runs_a_tool_call_then_answers() -> None:
    steps = [MissionStep(name="core", instruction="c", response_model=_Core)]
    responses = [_Resp(function_call=_fc("get_events_around", {"rec_t": 5})), _Resp(text='{"verdict":"yes"}')]
    client = _FakeClient(responses)
    dispatched: list[Any] = []

    def dispatch(fc: Any) -> dict[str, Any]:
        dispatched.append(fc)
        return {"events": []}

    out = await _run(client, steps, dispatch=dispatch)
    assert out["core"].verdict == "yes"
    assert [fc.args for fc in dispatched] == [{"rec_t": 5}]


@pytest.mark.asyncio
async def test_tool_budget_exhaustion_forces_a_final_tool_free_answer() -> None:
    # The model keeps calling the tool until the budget is gone; instead of hard-failing, the step forces one final
    # turn with tools removed and the model answers from what it has already seen.
    steps = [MissionStep(name="core", instruction="c", response_model=_Core)]
    # initial generate + 6 tool iterations = 7 function-call responses, then the forced tool-free answer.
    responses = [_Resp(function_call=_fc("get_events_around", {"rec_t": 5})) for _ in range(7)]
    responses.append(_Resp(text='{"verdict":"yes"}'))
    client = _FakeClient(responses)
    out = await _run(client, steps, dispatch=lambda fc: {"events": []})
    assert out["core"].verdict == "yes"
    assert len(client.models.calls) == 8  # 7 tool turns + 1 forced answer
    assert client.models.calls[0]["config"].tools is not None  # tool offered during the loop
    assert client.models.calls[-1]["config"].tools is None  # tools removed on the forced turn


@pytest.mark.asyncio
async def test_cached_tool_budget_exhaustion_forces_an_inline_tool_free_answer() -> None:
    # With the video cached, the forced final turn can't reuse the cache (Gemini rejects tools/tool_config alongside
    # cached_content). It must run inline with no tool and the video + preamble re-supplied — otherwise every
    # budget-exhausting cached scan hits a hard 400 and produces no observation.
    steps = [MissionStep(name="core", instruction="c", response_model=_Core)]
    responses = [_Resp(function_call=_fc("get_events_around", {"rec_t": 5})) for _ in range(7)]
    responses.append(_Resp(text='{"verdict":"yes"}'))
    client = _FakeClient(responses)
    out = await _run(client, steps, dispatch=lambda fc: {"events": []}, cache_name="caches/abc")
    assert out["core"].verdict == "yes"

    cached_turn, forced_turn = client.models.calls[0], client.models.calls[-1]
    assert cached_turn["config"].cached_content == "caches/abc"  # normal turns still use the cache
    assert cached_turn["contents"][0] != _VIDEO  # video lives in the cache, not inline

    assert forced_turn["config"].cached_content is None  # forced turn drops the cache...
    assert forced_turn["config"].tools is None and forced_turn["config"].tool_config is None  # ...and offers no tool
    assert forced_turn["contents"][0] == _VIDEO  # video + preamble re-supplied inline so context isn't lost
    assert forced_turn["contents"][1].text == "PRE"


@pytest.mark.asyncio
async def test_step_survives_a_response_with_no_candidates() -> None:
    # Gemini can return zero candidates (safety filter / content policy); the step must fail cleanly rather than
    # IndexError on candidates[0].
    class _Empty:
        candidates: list[Any] = []
        text = None

    steps = [MissionStep(name="core", instruction="c", response_model=_Core, required=False)]
    client = _FakeClient([_Empty(), _Empty()])  # type: ignore[list-item]  # both attempts come back empty
    out = await _run(client, steps)
    assert "core" not in out


@pytest.mark.asyncio
async def test_step_re_prompts_once_on_invalid_json() -> None:
    steps = [MissionStep(name="core", instruction="c", response_model=_Core)]
    client = _FakeClient([_Resp(text="not json"), _Resp(text='{"verdict":"yes"}')])
    out = await _run(client, steps)
    assert out["core"].verdict == "yes"
    assert len(client.models.calls) == 2  # initial + one re-prompt


@pytest.mark.asyncio
async def test_non_required_step_failure_is_skipped_not_raised() -> None:
    steps = [
        MissionStep(name="core", instruction="c", response_model=_Core),
        MissionStep(name="side", instruction="s", response_model=_Side, required=False),
    ]
    # core succeeds; side never validates across both attempts.
    client = _FakeClient([_Resp(text='{"verdict":"yes"}'), _Resp(text="bad"), _Resp(text="still bad")])
    out = await _run(client, steps)
    assert "core" in out
    assert "side" not in out


@pytest.mark.asyncio
async def test_failed_non_required_step_is_rolled_back_so_the_next_step_stays_clean() -> None:
    # extras (non-required) fails both attempts; signals must still run against a clean convo, with the failed
    # extras exchange rolled back rather than left as two consecutive user turns.
    steps = [
        MissionStep(name="summary", instruction="sum", response_model=_Core),
        MissionStep(name="extras", instruction="fac", response_model=_Side, required=False),
        MissionStep(name="signals", instruction="sig", response_model=_Side, required=False),
    ]
    client = _FakeClient(
        [
            _Resp(text='{"verdict":"yes"}'),  # summary ok
            _Resp(text="bad"),
            _Resp(text="still bad"),  # extras exhausts both attempts
            _Resp(text='{"note":"ok"}'),  # signals ok
        ]
    )
    out = await _run(client, steps)
    assert "summary" in out and "signals" in out and "extras" not in out
    # signals sees [video, preamble, summary instr, summary answer, signals instr] = 5; the failed extras turn rolled back.
    assert len(client.models.calls[-1]["contents"]) == 5


@pytest.mark.asyncio
async def test_required_step_failure_raises_validation_error() -> None:
    steps = [MissionStep(name="core", instruction="c", response_model=_Core)]
    client = _FakeClient([_Resp(text="bad"), _Resp(text="still bad")])
    with pytest.raises(ScannerFailureError, match="Required step 'core'") as caught:
        await _run(client, steps)
    assert caught.value.kind is FailureKind.VALIDATION_FAILED


@pytest.mark.asyncio
async def test_required_step_with_no_candidates_blames_the_provider_not_the_prompt() -> None:
    # Zero candidates is the provider declining to answer about this video, not a schema problem. Reporting it as
    # a validation failure would tell the user to rewrite a prompt that was never involved.
    class _Empty:
        candidates: list[Any] = []
        text = None

    steps = [MissionStep(name="core", instruction="c", response_model=_Core)]
    client = _FakeClient([_Empty(), _Empty()])  # type: ignore[list-item]
    with pytest.raises(ScannerFailureError) as caught:
        await _run(client, steps)
    assert caught.value.kind is FailureKind.PROVIDER_REJECTED


@pytest.mark.asyncio
async def test_semantic_validate_hook_triggers_a_re_prompt() -> None:
    def reject_no(parsed: BaseModel) -> str | None:
        return "verdict must be yes" if cast(_Core, parsed).verdict == "no" else None

    steps = [MissionStep(name="core", instruction="c", response_model=_Core, validate=reject_no)]
    client = _FakeClient([_Resp(text='{"verdict":"no"}'), _Resp(text='{"verdict":"yes"}')])
    out = await _run(client, steps)
    assert out["core"].verdict == "yes"


class TestMissionAttempts:
    """The per-step re-prompt argues with the model inside one conversation; this is the clean-slate re-ask around it."""

    @staticmethod
    def _failing_run(kind: FailureKind, fail_times: int) -> tuple[Any, list[str | None]]:
        calls: list[str | None] = []

        async def run(*, cache_name: str | None) -> dict[str, BaseModel]:
            calls.append(cache_name)
            if len(calls) <= fail_times:
                raise ScannerFailureError("rejected", kind=kind)
            return {"core": _Core(verdict="yes")}

        return run, calls

    @pytest.mark.asyncio
    async def test_validation_failure_gets_one_clean_re_ask(self) -> None:
        run, calls = self._failing_run(FailureKind.VALIDATION_FAILED, fail_times=1)
        out = await _run_mission_attempts(run=run, cache=None, model="m")
        assert cast(_Core, out["core"]).verdict == "yes"
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_re_asking_is_bounded(self) -> None:
        run, calls = self._failing_run(FailureKind.VALIDATION_FAILED, fail_times=99)
        with pytest.raises(ScannerFailureError):
            await _run_mission_attempts(run=run, cache=None, model="m")
        assert len(calls) == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kind",
        [FailureKind.PROVIDER_REJECTED, FailureKind.PROVIDER_TRANSIENT, FailureKind.INTERNAL_ERROR],
    )
    async def test_other_kinds_are_not_re_asked(self, kind: FailureKind) -> None:
        # Re-asking these would double the video spend for nothing: the provider isn't going to change its mind
        # mid-activity, and Temporal already owns the retry for the transient ones.
        run, calls = self._failing_run(kind, fail_times=1)
        with pytest.raises(ScannerFailureError):
            await _run_mission_attempts(run=run, cache=None, model="m")
        assert len(calls) == 1


class TestRunPass:
    """Which retry layer owns a cached-run failure. Transients belong to the Temporal activity retry (it backs
    off across the quota window); only cache-shaped failures get the one inline fallback. A blanket inline retry
    here would multiply with the other layers into many video re-sends per observation."""

    class _Cache:
        name = "cache-1"

    @staticmethod
    def _cached_run_failing_with(error: Exception) -> tuple[Any, list[str | None]]:
        calls: list[str | None] = []

        async def run(*, cache_name: str | None) -> dict[str, BaseModel]:
            calls.append(cache_name)
            if cache_name is not None:
                raise error
            return {"core": _Core(verdict="yes")}

        return run, calls

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            APIError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}),
            httpx.ConnectError("connection reset by peer"),
        ],
    )
    async def test_transient_provider_error_is_not_retried_inline(self, error: Exception) -> None:
        run, calls = self._cached_run_failing_with(error)
        with pytest.raises(type(error)):
            await _run_pass(run=run, cache=self._Cache(), model="m")
        assert calls == ["cache-1"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            APIError(403, {"error": {"message": "CachedContent not found"}}),
            ValueError("unrecognized SDK failure"),
        ],
    )
    async def test_cache_shaped_failure_falls_back_inline_once(self, error: Exception) -> None:
        run, calls = self._cached_run_failing_with(error)
        out = await _run_pass(run=run, cache=self._Cache(), model="m")
        assert cast(_Core, out["core"]).verdict == "yes"
        assert calls == ["cache-1", None]


_MODULE = "products.replay_vision.backend.temporal.activities.call_scanner_provider"


def _verification_counts() -> dict[tuple[str, str], float]:
    return {
        (sample.labels["mode"], sample.labels["outcome"]): sample.value
        for family in REPLAY_VISION_VERIFICATION_OUTCOMES.collect()
        for sample in family.samples
        if sample.name == "replay_vision_verification_outcomes_total"
    }


@frozen
class _ScanRun:
    outcome: _MissionOutcome
    # Runner calls in order, then the cache deletion.
    calls: list[Any]
    # Verification counter increments during the scan, keyed by (mode, outcome).
    counted: dict[tuple[str, str], float]


class TestVerifyPositives:
    class _Cache:
        name = "caches/abc"

    @staticmethod
    def _answer(verdict: str) -> MonitorLlmResponse:
        return MonitorLlmResponse(reasoning=f"because {verdict}", verdict=cast(Any, verdict), confidence=0.8)

    async def _scan(
        self,
        *,
        mode: str,
        answers: list[str | Exception],
        allow_inconclusive: bool = False,
        cached: bool = True,
        emits_signals: bool = False,
        budget_seconds: float | None = None,
    ) -> _ScanRun:
        # `answers[0]` is the first pass; the rest are the verify draws in order.
        scanner = MonitorScanner(
            prompt="did it happen", allow_inconclusive=allow_inconclusive, emits_signals=emits_signals
        )
        snapshot = ScannerSnapshot(
            name="m",
            scanner_type=ScannerType.MONITOR,
            scanner_version=1,
            model="gemini-3-flash-preview",
            provider="gemini",
            emits_signals=emits_signals,
            scanner_config={"prompt": "did it happen"},
            verify_positives=mode,
        )
        pending = iter(answers)
        calls: list[Any] = []

        async def fake_run_steps(*, steps: list[MissionStep], cache_name: str | None, **_: Any) -> dict[str, BaseModel]:
            calls.append({"steps": [step.name for step in steps], "cache_name": cache_name})
            # A verify draw must keep the core step's semantic check, or an `inconclusive` the scanner forbids
            # would count as a vote.
            assert all(step.required and step.validate is not None for step in steps if step.name != "signals")
            answer = next(pending)
            if isinstance(answer, Exception):
                raise answer
            return {step.name: self._answer(answer) for step in steps if step.name != "signals"}

        async def fake_delete(*_: Any) -> None:
            calls.append("delete_cache")

        before = _verification_counts()
        with (
            patch(f"{_MODULE}.genai.AsyncClient"),
            patch(f"{_MODULE}.GoogleGenAIClient"),
            patch(f"{_MODULE}.build_events_index", return_value={}),
            patch(
                f"{_MODULE}._maybe_create_video_cache", new=AsyncMock(return_value=self._Cache() if cached else None)
            ),
            patch(f"{_MODULE}._delete_video_cache", new=fake_delete),
            patch(f"{_MODULE}._run_steps", new=fake_run_steps),
            patch(f"{_MODULE}._remaining_verify_budget_seconds", return_value=budget_seconds),
        ):
            outcome = await _run_mission(
                scanner=scanner,
                snapshot=snapshot,
                video_part=_VIDEO,
                preamble_text="PRE",
                team_id=1,
                llm_inputs=MagicMock(),
                trace_id="trace-1",
            )
        counted = {
            key: value - before.get(key, 0.0)
            for key, value in _verification_counts().items()
            if value != before.get(key, 0.0)
        }
        return _ScanRun(outcome=outcome, calls=calls, counted=counted)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mode,answers",
        [
            ("off", ["yes"]),
            ("Enforce", ["yes"]),
            ("enforce", ["no"]),
            ("enforce", ["inconclusive"]),
        ],
    )
    async def test_only_a_positive_under_a_live_mode_is_verified(
        self, mode: str, answers: list[str | Exception]
    ) -> None:
        run = await self._scan(mode=mode, answers=answers, allow_inconclusive=True)
        assert len(run.calls) == 2  # the first pass and the cache deletion
        assert cast(MonitorOutput, run.outcome.finalized).verdict == answers[0]
        assert run.outcome.verification is None
        assert run.counted == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mode,draws,allow_inconclusive,resolved,served,outcome_label",
        [
            ("shadow", ["yes", "yes"], False, "yes", "yes", "agreed"),
            ("enforce", ["yes", "yes"], False, "yes", "yes", "agreed"),
            ("enforce", ["yes", "no", "no"], False, "no", "no", "tiebreak_flipped"),
            ("shadow", ["yes", "no", "no"], False, "no", "yes", "tiebreak_flipped"),
            ("enforce", ["yes", "no", "yes"], False, "yes", "yes", "tiebreak_kept"),
            ("enforce", ["yes", "no", "inconclusive"], True, "inconclusive", "inconclusive", "tiebreak_flipped"),
        ],
    )
    async def test_majority_of_up_to_three_draws_settles_the_verdict(
        self,
        mode: str,
        draws: list[str],
        allow_inconclusive: bool,
        resolved: str,
        served: str,
        outcome_label: str,
    ) -> None:
        run = await self._scan(mode=mode, answers=list(draws), allow_inconclusive=allow_inconclusive)
        finalized = cast(MonitorOutput, run.outcome.finalized)
        # `enforce` serves the whole winning draw, reasoning included, not just its verdict.
        assert (finalized.verdict, finalized.reasoning) == (served, f"because {served}")
        assert run.outcome.verification == VerificationRecord(
            mode=mode, draws=cast(Any, draws), resolved_verdict=cast(Any, resolved), served_verdict=cast(Any, served)
        )
        assert len(run.calls) == len(draws) + 1
        assert run.counted == {(mode, outcome_label): 1.0}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "answers,reason",
        [
            (["yes", ScannerFailureError("rejected", kind=FailureKind.VALIDATION_FAILED)], "draw_failed"),
            (
                ["yes", "no", APIError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})],
                "draw_failed",
            ),
            # `asyncio.wait_for` raises this when a draw runs past the activity budget.
            (["yes", TimeoutError()], "draw_failed"),
        ],
    )
    async def test_a_failed_draw_keeps_the_first_verdict_and_never_raises(
        self, answers: list[str | Exception], reason: str
    ) -> None:
        run = await self._scan(mode="enforce", answers=answers)
        assert cast(MonitorOutput, run.outcome.finalized).verdict == "yes"
        assert run.outcome.verification == VerificationRecord(
            mode="enforce",
            draws=cast(Any, [answer for answer in answers if isinstance(answer, str)]),
            resolved_verdict="yes",
            served_verdict="yes",
            skipped_reason=reason,
        )
        assert len(run.calls) == len(answers) + 1
        assert run.counted == {("enforce", reason): 1.0}

    @pytest.mark.asyncio
    async def test_without_a_cache_the_first_pass_stands(self) -> None:
        # A re-draw without the cache would re-send the whole video; that spend is not worth one extra vote.
        run = await self._scan(mode="enforce", answers=["yes"], cached=False)
        assert len(run.calls) == 1
        assert run.outcome.verification == VerificationRecord(
            mode="enforce", draws=["yes"], resolved_verdict="yes", served_verdict="yes", skipped_reason="no_cache"
        )
        assert run.counted == {("enforce", "no_cache"): 1.0}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("budget_seconds,draws_taken", [(0.0, 0), (-5.0, 0), (30.0, 1)])
    async def test_a_draw_never_starts_past_the_activity_budget(self, budget_seconds: float, draws_taken: int) -> None:
        # The activity timeout would fail the whole scan, first verdict included, so a draw with no time left is skipped.
        run = await self._scan(mode="enforce", answers=["yes", "yes"], budget_seconds=budget_seconds)
        assert len(run.calls) == 2 + draws_taken
        assert cast(MonitorOutput, run.outcome.finalized).verdict == "yes"
        if draws_taken == 0:
            assert run.outcome.verification == VerificationRecord(
                mode="enforce", draws=["yes"], resolved_verdict="yes", served_verdict="yes", skipped_reason="no_budget"
            )
            assert run.counted == {("enforce", "no_budget"): 1.0}
        else:
            assert run.counted == {("enforce", "agreed"): 1.0}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "start_to_close,elapsed,expected",
        [
            (dt.timedelta(minutes=20), dt.timedelta(minutes=5), 14 * 60.0),
            (dt.timedelta(minutes=20), dt.timedelta(minutes=19, seconds=30), -30.0),
            (None, dt.timedelta(minutes=5), None),
        ],
    )
    async def test_remaining_budget_reads_the_activity_timeout(
        self, start_to_close: dt.timedelta | None, elapsed: dt.timedelta, expected: float | None
    ) -> None:
        now = timezone.now()
        env = ActivityEnvironment()
        env.info = dataclasses.replace(env.info, start_to_close_timeout=start_to_close, started_time=now - elapsed)

        async def read_budget() -> float | None:
            return _remaining_verify_budget_seconds()

        with freeze_time(now):
            assert await env.run(read_budget) == expected

    def test_remaining_budget_is_unbounded_outside_an_activity(self) -> None:
        assert _remaining_verify_budget_seconds() is None

    @pytest.mark.asyncio
    async def test_verify_draws_are_blind_core_only_turns_over_the_live_cache(self) -> None:
        run = await self._scan(mode="enforce", answers=["yes", "no", "yes"], emits_signals=True)
        assert run.calls == [
            {"steps": ["core", "signals"], "cache_name": "caches/abc"},
            {"steps": ["core_verify_2"], "cache_name": "caches/abc"},
            {"steps": ["core_verify_3"], "cache_name": "caches/abc"},
            "delete_cache",
        ]


class TestStepConfig:
    def test_inline_path_carries_tools_and_no_cache(self) -> None:
        config = _step_config(MissionStep(name="core", instruction="c", response_model=_Core), cache_name=None)
        assert config.tools is not None
        assert config.cached_content is None
        assert config.response_json_schema is not None
        assert config.thinking_config is not None and config.thinking_config.include_thoughts is True

    def test_cached_path_references_the_cache_and_omits_tools(self) -> None:
        config = _step_config(MissionStep(name="core", instruction="c", response_model=_Core), cache_name="caches/abc")
        # Tools live in the cache; re-declaring them in the config alongside cached_content is rejected by Gemini.
        assert config.tools is None
        assert config.cached_content == "caches/abc"
        assert config.response_json_schema is not None

    @pytest.mark.parametrize("cache_name", [None, "caches/abc"])
    def test_forced_turn_never_references_the_cache_or_sets_tool_config(self, cache_name: str | None) -> None:
        # Gemini rejects a request that sets tools, tool_config, or system_instruction alongside cached_content with
        # a hard 400. The forced final turn must run inline with the tool simply absent, even on a cached run.
        config = _step_config(
            MissionStep(name="core", instruction="c", response_model=_Core), cache_name=cache_name, allow_tools=False
        )
        assert config.tools is None
        assert config.tool_config is None
        assert config.cached_content is None
        assert config.response_json_schema is not None


@pytest.mark.asyncio
async def test_video_cache_creation_is_best_effort() -> None:
    class _BoomCaches:
        async def create(self, **kwargs: Any) -> Any:
            raise RuntimeError("video too short to cache")

    class _BoomClient:
        aio = type("Aio", (), {"caches": _BoomCaches()})()

    # A cache that can't be created (e.g. too-short video) degrades to None, not an error.
    result = await _maybe_create_video_cache(cast(Any, _BoomClient()), "models/gemini-3-flash-preview", _VIDEO, "PRE")
    assert result is None
