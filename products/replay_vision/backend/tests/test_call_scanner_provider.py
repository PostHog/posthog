from collections.abc import Callable
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.activities.call_scanner_provider import (
    _key_moment_session_ms,
    _maybe_create_video_cache,
    _run_mission,
    _run_mission_attempts,
    _run_pass,
    _run_steps,
    _step_config,
)
from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError
from products.replay_vision.backend.temporal.lookups import Lookup, LookupPlan
from products.replay_vision.backend.temporal.scanners.base import (
    STEP_MAX_OUTPUT_TOKENS,
    MissionStep,
    SignalFinding,
    SignalsResponse,
)
from products.replay_vision.backend.temporal.scanners.monitor import MonitorLlmResponse, MonitorOutput, MonitorScanner
from products.replay_vision.backend.temporal.types import ScannerSnapshot
from products.replay_vision.backend.temporal.video_clock import ActiveSpan, VideoClock

_LABELS = {"provider": "gemini", "model": "gemini-3-flash-preview", "scanner_type": "monitor"}
# The driver treats the video part opaquely (just appended to the conversation), so a sentinel is fine.
_IDENTITY_CLOCK = VideoClock(spans=())
_VIDEO: Any = "VIDEO"


class _Core(BaseModel):
    verdict: str


class _Side(BaseModel):
    note: str


class _FakeContent:
    def __init__(self) -> None:
        self.parts = [type("Part", (), {})()]


class _Resp:
    """Minimal genai response: `.text`, `.candidates[0].content.parts`, and an optional finish reason."""

    def __init__(self, text: str = "", finish_reason: Any = None, empty_content: bool = False) -> None:
        content = None if empty_content else _FakeContent()
        self.candidates = [type("Cand", (), {"content": content, "finish_reason": finish_reason})()]
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


async def _run(
    client: _FakeClient,
    steps: list[MissionStep],
    look_up: Callable[[LookupPlan], list[dict[str, Any]]] = lambda plan: [],
    cache_name=None,
):
    return await _run_steps(
        client=client,
        model="models/gemini-3-flash-preview",
        steps=steps,
        video_part=_VIDEO,
        preamble_text="PRE",
        cache_name=cache_name,
        team_id=1,
        metric_labels=_LABELS,
        trace_id="trace-1",
        look_up=look_up,
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
            video_clock=_IDENTITY_CLOCK,
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
async def test_lookup_round_answers_the_whole_plan_in_one_turn_on_the_cache() -> None:
    # The answer turn has to stay on the cached prefix: an inline turn re-sends the whole video at full price.
    plan = LookupPlan(lookups=[Lookup(source="events", vid_t=12), Lookup(source="network", vid_t=40, window_s=5)])
    planned: list[LookupPlan] = []

    def look_up(received: LookupPlan) -> list[dict[str, Any]]:
        planned.append(received)
        return [{"source": "events", "vid_t": 12, "window_s": 30, "events": [{"event": "$rageclick"}]}]

    steps = [MissionStep(name="core", instruction="do core", response_model=_Core, plan_instruction="plan core")]
    client = _FakeClient([_Resp(text=plan.model_dump_json()), _Resp(text='{"verdict":"yes"}')])
    out = await _run(client, steps, look_up=look_up, cache_name="caches/abc")

    assert out["core"].verdict == "yes"
    assert planned == [plan]
    plan_turn, answer_turn = client.models.calls
    assert [call["config"].cached_content for call in client.models.calls] == ["caches/abc", "caches/abc"]
    assert plan_turn["contents"][-1].text == "plan core"
    assert "$rageclick" in answer_turn["contents"][-1].text


@pytest.mark.asyncio
async def test_a_failed_lookup_plan_answers_the_step_without_lookups() -> None:
    look_up = MagicMock(return_value=[])
    steps = [MissionStep(name="core", instruction="do core", response_model=_Core, plan_instruction="plan core")]
    client = _FakeClient([_Resp(text="bad"), _Resp(text="still bad"), _Resp(text='{"verdict":"yes"}')])
    out = await _run(client, steps, look_up=look_up)

    assert out["core"].verdict == "yes"
    look_up.assert_not_called()
    assert [getattr(item, "text", item) for item in client.models.calls[-1]["contents"]] == ["VIDEO", "PRE", "do core"]


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_content", [False, True])
async def test_output_cap_hit_re_prompts_for_briefer_reasoning(empty_content: bool) -> None:
    # A MAX_TOKENS finish means thinking ate the cap and the JSON never arrived. The generic "raw JSON only"
    # correction would re-run the same reasoning into the same wall, so the re-prompt has to name the cause. When
    # thinking consumed the whole cap the candidate has no content at all; resending that would 400 the retry.
    steps = [MissionStep(name="core", instruction="c", response_model=_Core)]
    responses = [
        _Resp(
            text="" if empty_content else '{"verd',
            finish_reason=types.FinishReason.MAX_TOKENS,
            empty_content=empty_content,
        ),
        _Resp(text='{"verdict":"yes"}'),
    ]
    client = _FakeClient(responses)
    with patch(f"{_MODULE}.record_provider_call") as record:
        out = await _run(client, steps)
    assert out["core"].verdict == "yes"
    retry_contents = client.models.calls[1]["contents"]
    assert "ran out of output tokens" in retry_contents[-1].text
    assert all(item is not None for item in retry_contents)
    assert [call.kwargs["outcome"] for call in record.call_args_list] == ["output_cap_hit", "ok"]


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
@pytest.mark.parametrize(
    "duration_seconds,end_times,expected_end",
    [
        (10.9, [10], 10),
        (10.0, [10], 10),
        (0.9, [0], 0),
        (10.9, [11, 11], None),
        (10.9, [11, 10], 10),
        (None, [0, 0], None),
        (0.0, [0, 0], None),
        (-1.0, [0, 0], None),
        (float("nan"), [0, 0], None),
        (float("inf"), [0, 0], None),
        (None, [None], None),
    ],
)
async def test_signal_timestamps_use_recording_duration(
    duration_seconds: float | None, end_times: list[int | None], expected_end: int | None
) -> None:
    scanner = MonitorScanner(prompt="Did the dialog block input?", emits_signals=True)
    snapshot = ScannerSnapshot(
        name="monitor",
        scanner_type=ScannerType.MONITOR,
        scanner_version=1,
        model="gemini-3-flash-preview",
        provider="gemini",
        emits_signals=True,
        scanner_config={"prompt": scanner.prompt},
    )
    signal = SignalFinding(
        problem_type="bug",
        headline="Blank dialog blocks the editor",
        start_time=0,
        end_time=0,
        url="https://example.com/editor",
        description="A blank dialog covers the editor and prevents input.",
        confidence=0.9,
    )
    core = MonitorLlmResponse(
        verdict="yes", reasoning="The dialog blocked input.", confidence=0.9, thumbnail_t=7, key_moment_t=5
    )
    client = _FakeClient(
        [_Resp(text=LookupPlan().model_dump_json()), _Resp(text=core.model_dump_json())]
        + [
            _Resp(
                text=SignalsResponse(
                    signals=[] if end_time is None else [signal.model_copy(update={"end_time": end_time})]
                ).model_dump_json()
            )
            for end_time in end_times
        ]
    )
    module = "products.replay_vision.backend.temporal.activities.call_scanner_provider"
    with (
        patch(f"{module}.genai.AsyncClient", return_value=client),
        patch(f"{module}.GoogleGenAIClient"),
        patch(f"{module}.build_events_index", return_value={}),
        patch(f"{module}._maybe_create_video_cache", new=AsyncMock(return_value=None)),
    ):
        outcome = await _run_mission(
            scanner=scanner,
            snapshot=snapshot,
            video_part=_VIDEO,
            video_clock=_IDENTITY_CLOCK,
            preamble_text="PRE",
            team_id=1,
            llm_inputs=MagicMock(metadata=MagicMock(duration_seconds=duration_seconds)),
            trace_id="trace-1",
        )
    assert cast(MonitorOutput, outcome.finalized).verdict == "yes"
    assert outcome.signals == ([] if expected_end is None else [signal.model_copy(update={"end_time": expected_end})])
    # The pick rides the core answer, so no turn of its own is spent on it.
    assert outcome.thumbnail_video_s == 7
    assert outcome.key_moment_video_s == 5
    assert len(client.models.calls) == 2 + len(end_times)


# The render cut 10s-40s of the session, so video second 15 shows session second 45.
_CUT_CLOCK = VideoClock(
    spans=(
        ActiveSpan(session_from_s=0, session_to_s=10, video_from_s=0, video_to_s=10),
        ActiveSpan(session_from_s=40, session_to_s=60, video_from_s=10, video_to_s=30),
    )
)


@pytest.mark.parametrize(
    "video_s, duration_ms, clock, expected",
    [
        pytest.param(None, 20_000, _IDENTITY_CLOCK, None, id="skipped pick stays unset"),
        pytest.param(12, 20_000, _IDENTITY_CLOCK, 12_000, id="uncut render keeps the same second"),
        pytest.param(20, 20_000, _IDENTITY_CLOCK, 20_000, id="the final second is still a moment"),
        pytest.param(21, 20_000, _IDENTITY_CLOCK, None, id="a time past the recording is dropped"),
        pytest.param(15, 60_000, _CUT_CLOCK, 45_000, id="a cut render maps onto the session clock"),
        pytest.param(31, 60_000, _CUT_CLOCK, None, id="a time past the video is dropped, not clamped"),
    ],
)
def test_key_moment_moves_onto_the_session_clock(
    video_s: int | None, duration_ms: int, clock: VideoClock, expected: int | None
) -> None:
    assert _key_moment_session_ms(video_s, duration_ms, clock) == expected


@pytest.mark.asyncio
async def test_a_provider_error_on_a_non_required_step_leaves_the_scan_standing() -> None:
    # A provider blip on the last, optional turn used to fail the whole paid-for scan.
    steps = [
        MissionStep(name="summary", instruction="sum", response_model=_Core),
        MissionStep(name="media", instruction="pick", response_model=_Side, required=False),
    ]

    class _ExplodingModels(_FakeModels):
        async def generate_content(self, **kwargs: Any) -> _Resp:
            if len(self.calls) >= 1:
                raise RuntimeError("provider is down")
            return await super().generate_content(**kwargs)

    client = _FakeClient([_Resp(text='{"verdict":"yes"}')])
    client.models = _ExplodingModels([_Resp(text='{"verdict":"yes"}')])

    out = await _run(client, steps)

    assert "summary" in out
    assert "media" not in out


@pytest.mark.asyncio
async def test_a_provider_error_on_a_required_step_still_fails_the_scan() -> None:
    steps = [MissionStep(name="summary", instruction="sum", response_model=_Core)]

    class _ExplodingModels(_FakeModels):
        async def generate_content(self, **kwargs: Any) -> _Resp:
            raise RuntimeError("provider is down")

    client = _FakeClient([])
    client.models = _ExplodingModels([])

    with pytest.raises(RuntimeError):
        await _run(client, steps)


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


class TestStepConfig:
    def test_inline_path_sets_no_cache(self) -> None:
        config = _step_config(MissionStep(name="core", instruction="c", response_model=_Core), cache_name=None)
        assert config.cached_content is None
        assert config.response_json_schema is not None
        assert config.thinking_config is not None and config.thinking_config.include_thoughts is True
        assert config.max_output_tokens == STEP_MAX_OUTPUT_TOKENS


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


@pytest.mark.asyncio
async def test_apply_experiment_scan_context_injects_into_experiment_scanners_only() -> None:
    # The injected fields are exclude=True, so this per-scan context is the only way the prompt
    # ever learns the variant; a broken injection silently degrades every experiment scan.
    from uuid import uuid4

    from products.replay_vision.backend.temporal.activities.call_scanner_provider import _apply_experiment_scan_context
    from products.replay_vision.backend.temporal.scanners.experiment import ExperimentScanner
    from products.replay_vision.backend.temporal.types import CallScannerProviderInputs

    inputs = CallScannerProviderInputs(
        team_id=1,
        observation_id=uuid4(),
        exported_asset_id=1,
        file_uri="file://x",
        mime_type="video/mp4",
        experiment_variant="test",
        experiment_context={
            "id": 42,
            "name": "Checkout CTA copy",
            "description": "",
            "feature_flag_key": "checkout-cta",
            "variants": [{"key": "test", "description": "", "rollout_percentage": 50.0}],
            "primary_metric_names": [],
        },
    )

    experiment_scanner = ExperimentScanner(prompt="p", experiment_id=42)
    injected = await _apply_experiment_scan_context(experiment_scanner, inputs)
    assert isinstance(injected, ExperimentScanner)
    assert injected.session_variant == "test"
    assert injected.experiment_context is not None and injected.experiment_context["name"] == "Checkout CTA copy"
    assert "`test` variant" in injected.core_steps()[0].instruction

    monitor = MonitorScanner(prompt="p")
    assert await _apply_experiment_scan_context(monitor, inputs) is monitor


@pytest.mark.asyncio
async def test_evaluation_calls_fall_back_to_the_persisted_attribution() -> None:
    # Evaluations re-scan a rated session and dispatch no resolve activity; without the fallback
    # they would test a suggested prompt without its experiment block.
    from uuid import uuid4

    from products.replay_vision.backend.temporal.activities.call_scanner_provider import _apply_experiment_scan_context
    from products.replay_vision.backend.temporal.scanners.experiment import ExperimentScanner
    from products.replay_vision.backend.temporal.types import CallScannerProviderInputs

    inputs = CallScannerProviderInputs(
        team_id=1, observation_id=uuid4(), exported_asset_id=1, file_uri="file://x", mime_type="video/mp4"
    )
    with patch(
        "products.replay_vision.backend.temporal.activities.call_scanner_provider._load_persisted_experiment_context",
        return_value=("control", None),
    ):
        injected = await _apply_experiment_scan_context(ExperimentScanner(prompt="p", experiment_id=42), inputs)

    assert isinstance(injected, ExperimentScanner)
    assert injected.session_variant == "control"
