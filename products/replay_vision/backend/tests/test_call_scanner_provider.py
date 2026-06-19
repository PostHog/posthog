from typing import Any

import pytest

from pydantic import BaseModel

from products.replay_vision.backend.temporal.activities.call_scanner_provider import (
    _maybe_create_video_cache,
    _run_steps,
    _step_config,
)
from products.replay_vision.backend.temporal.errors import ScannerFailureError
from products.replay_vision.backend.temporal.scanners.base import MissionStep

_LABELS = {"provider": "gemini", "model": "gemini-3-flash-preview", "scanner_type": "monitor"}


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
        video_part="VIDEO",
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
async def test_required_step_failure_raises_validation_error() -> None:
    steps = [MissionStep(name="core", instruction="c", response_model=_Core)]
    client = _FakeClient([_Resp(text="bad"), _Resp(text="still bad")])
    with pytest.raises(ScannerFailureError, match="Required step 'core'"):
        await _run(client, steps)


@pytest.mark.asyncio
async def test_semantic_validate_hook_triggers_a_re_prompt() -> None:
    def reject_no(parsed: _Core) -> str | None:
        return "verdict must be yes" if parsed.verdict == "no" else None

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
    result = await _maybe_create_video_cache(_BoomClient(), "models/gemini-3-flash-preview", "VIDEO", "PRE")
    assert result is None
