from typing import Any, cast

import pytest

from google.genai.errors import ServerError
from pydantic import BaseModel
from temporalio.testing import ActivityEnvironment

from products.replay_vision.backend.temporal.activities import call_scanner_provider as module
from products.replay_vision.backend.temporal.activities.call_scanner_provider import (
    _maybe_create_video_cache,
    _run_steps,
    _step_config,
    call_scanner_provider_activity,
)
from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError
from products.replay_vision.backend.temporal.scanners.base import MissionStep

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
    )


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
    # facets (non-required) fails both attempts; signals must still run against a clean convo, with the failed
    # facets exchange rolled back rather than left as two consecutive user turns.
    steps = [
        MissionStep(name="summary", instruction="sum", response_model=_Core),
        MissionStep(name="facets", instruction="fac", response_model=_Side, required=False),
        MissionStep(name="signals", instruction="sig", response_model=_Side, required=False),
    ]
    client = _FakeClient(
        [
            _Resp(text='{"verdict":"yes"}'),  # summary ok
            _Resp(text="bad"),
            _Resp(text="still bad"),  # facets exhausts both attempts
            _Resp(text='{"note":"ok"}'),  # signals ok
        ]
    )
    out = await _run(client, steps)
    assert "summary" in out and "signals" in out and "facets" not in out
    # signals sees [video, preamble, summary instr, summary answer, signals instr] = 5; the failed facets turn rolled back.
    assert len(client.models.calls[-1]["contents"]) == 5


@pytest.mark.asyncio
async def test_gemini_server_error_is_classified_as_provider_transient(monkeypatch: Any) -> None:
    # A Gemini 5xx (e.g. a 503) that escapes the scanner run must surface as a retryable provider_transient failure.
    # Without this it would propagate raw and the workflow would misclassify it as internal_error.
    async def _boom(_inputs: Any) -> Any:
        raise ServerError(503, {"error": {"message": "The service is currently unavailable"}})

    monkeypatch.setattr(module, "_call_scanner_provider", _boom)
    with pytest.raises(ScannerFailureError) as exc_info:
        await ActivityEnvironment().run(call_scanner_provider_activity, cast(Any, None))
    assert exc_info.value.kind == FailureKind.PROVIDER_TRANSIENT


@pytest.mark.asyncio
async def test_required_step_failure_raises_validation_error() -> None:
    steps = [MissionStep(name="core", instruction="c", response_model=_Core)]
    client = _FakeClient([_Resp(text="bad"), _Resp(text="still bad")])
    with pytest.raises(ScannerFailureError, match="Required step 'core'"):
        await _run(client, steps)


@pytest.mark.asyncio
async def test_semantic_validate_hook_triggers_a_re_prompt() -> None:
    def reject_no(parsed: BaseModel) -> str | None:
        return "verdict must be yes" if cast(_Core, parsed).verdict == "no" else None

    steps = [MissionStep(name="core", instruction="c", response_model=_Core, validate=reject_no)]
    client = _FakeClient([_Resp(text='{"verdict":"no"}'), _Resp(text='{"verdict":"yes"}')])
    out = await _run(client, steps)
    assert out["core"].verdict == "yes"


class TestStepConfig:
    def test_inline_path_carries_tools_and_no_cache(self) -> None:
        config = _step_config(MissionStep(name="core", instruction="c", response_model=_Core), cache_name=None)
        assert config.tools is not None
        assert config.cached_content is None
        assert config.response_json_schema is not None

    def test_cached_path_references_the_cache_and_omits_tools(self) -> None:
        config = _step_config(MissionStep(name="core", instruction="c", response_model=_Core), cache_name="caches/abc")
        # Tools live in the cache; re-declaring them in the config alongside cached_content is rejected by Gemini.
        assert config.tools is None
        assert config.cached_content == "caches/abc"
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
