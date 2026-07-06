"""Unit tests for cassettes, replay/recording sessions, and session injection.

Deterministic and DB-free. Run with::

    DJANGO_SETTINGS_MODULE=posthog.settings DEBUG=1 TEST=1 .venv/bin/pytest \
      products/signals/eval/agentic/ -o python_files="test_*.py" -o python_functions="test_*"
"""

from __future__ import annotations

import asyncio

import pytest
from unittest import mock

from pydantic import BaseModel

from products.signals.eval.agentic.cassette import (
    Cassette,
    CassetteDriftError,
    CassetteExhaustedError,
    RecordedTurn,
    TurnCursor,
    prompt_fingerprint,
)
from products.signals.eval.agentic.session_backends import (
    MultiTurnSession,
    RecordingMultiTurnSession,
    ReplayMultiTurnSession,
    active_cassette,
    active_recorder,
    inject_session,
    recorder_to_cassette,
)


class _Probe(BaseModel):
    value: int
    label: str


def _cassette(*raw_texts: str, step: str = "research") -> Cassette:
    # Empty label/model, no prompt_sha: the minimal hand-authored shape, so drift checks skip.
    return Cassette(
        case_id="t",
        step=step,
        turns=[RecordedTurn(index=i, label="", model="", raw_text=t) for i, t in enumerate(raw_texts)],
    )


def test_cassette_round_trip(tmp_path):
    cassette = _cassette('{"value": 1, "label": "a"}', '{"value": 2, "label": "b"}')
    path = tmp_path / "c.json"
    cassette.save(path)
    loaded = Cassette.load(path)
    assert loaded.case_id == "t"
    assert [t.raw_text for t in loaded.turns] == [t.raw_text for t in cassette.turns]


def test_turn_cursor_exhaustion():
    cursor = TurnCursor(_cassette('{"value": 1, "label": "a"}'))
    cursor.next(label="x", model="_Probe")
    try:
        cursor.next(label="y", model="_Probe")
    except CassetteExhaustedError as exc:
        assert "re-record" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected CassetteExhaustedError")


def test_prompt_fingerprint_stable():
    assert prompt_fingerprint("abc") == prompt_fingerprint("abc")
    assert prompt_fingerprint("abc") != prompt_fingerprint("abd")


@pytest.mark.parametrize(
    "recorded,requested,fragment",
    [
        (
            {"label": "actionability", "model": "ActionabilityAssessment"},
            {"label": "priority", "model": "ActionabilityAssessment"},
            "requested label='priority' but cassette recorded label='actionability'",
        ),
        (
            {"label": "", "model": "SignalFinding"},
            {"label": "initial turn", "model": "ActionabilityAssessment"},
            "requested model='ActionabilityAssessment' but cassette recorded model='SignalFinding'",
        ),
        (
            {"label": "", "model": "", "prompt_sha": prompt_fingerprint("recorded prompt")},
            {"label": "x", "model": "y", "prompt": "changed prompt"},
            "prompt fingerprint",
        ),
    ],
)
def test_turn_cursor_detects_drift(recorded: dict, requested: dict, fragment: str):
    cassette = Cassette(case_id="t", step="research", turns=[RecordedTurn(index=0, raw_text="{}", **recorded)])
    with pytest.raises(CassetteDriftError) as exc_info:
        TurnCursor(cassette).next(**requested)
    assert fragment in str(exc_info.value)
    assert "re-record" in str(exc_info.value)


def test_replay_session_validates_via_real_parser():
    """Replay must run the recorded text through the real Pydantic validation path."""

    async def run() -> tuple[_Probe, _Probe]:
        cassette = _cassette('{"value": 1, "label": "first"}', '{"value": 2, "label": "second"}')
        with active_cassette(cassette):
            session, first = await ReplayMultiTurnSession.start(prompt="p", context=None, model=_Probe)
            second = await session.send_followup("f", _Probe, label="t1")
        return first, second

    first, second = asyncio.run(run())
    assert (first.value, first.label) == (1, "first")
    assert (second.value, second.label) == (2, "second")


def test_replay_session_rejects_invalid_recorded_text():
    """A cassette that no longer validates against the schema is a real, surfaced failure."""

    async def run() -> None:
        cassette = _cassette('{"value": "not-an-int", "label": "x"}')
        with active_cassette(cassette):
            await ReplayMultiTurnSession.start(prompt="p", context=None, model=_Probe)

    try:
        asyncio.run(run())
    except Exception as exc:
        assert "validation" in str(exc).lower() or "value" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("expected a validation error from replay")


def test_replay_raw_paths():
    async def run() -> tuple[str, str]:
        cassette = _cassette("raw-one", "raw-two")
        with active_cassette(cassette):
            session, first = await ReplayMultiTurnSession.start_raw(prompt="p", context=None)
            second = await session.send_followup_raw("f", label="t")
        return first, second

    first, second = asyncio.run(run())
    assert (first, second) == ("raw-one", "raw-two")


def test_recording_session_records_each_structured_turn_once_and_round_trips():
    # The structured path routes through the raw hooks — recording in both layers used to
    # double-record every turn, producing cassettes that desynced on replay.
    raw_turns = ['{"value": 1, "label": "first"}', '{"value": 2, "label": "second"}']

    async def _fake_start_raw(cls, prompt, context, **kwargs):
        return cls.__new__(cls), raw_turns[0]

    async def _fake_send_followup_raw(self, message, *, label=""):
        return raw_turns[1]

    async def record():
        with (
            mock.patch.object(MultiTurnSession, "start_raw", classmethod(_fake_start_raw)),
            mock.patch.object(MultiTurnSession, "send_followup_raw", _fake_send_followup_raw),
            active_recorder("t", "research") as recorder,
        ):
            session, first = await RecordingMultiTurnSession.start(prompt="p-initial", context=None, model=_Probe)
            second = await session.send_followup("p-followup", _Probe, label="t1")
        return recorder, first, second

    recorder, first, second = asyncio.run(record())
    assert (first.value, second.value) == (1, 2)
    assert [(t.label, t.model) for t in recorder.turns] == [("initial turn", "_Probe"), ("t1", "_Probe")]
    assert [t.prompt_sha for t in recorder.turns] == [prompt_fingerprint("p-initial"), prompt_fingerprint("p-followup")]

    async def replay():
        with active_cassette(recorder_to_cassette(recorder)):
            session, first = await ReplayMultiTurnSession.start(prompt="p-initial", context=None, model=_Probe)
            second = await session.send_followup("p-followup", _Probe, label="t1")
        return first, second

    replayed_first, replayed_second = asyncio.run(replay())
    assert (replayed_first.value, replayed_second.value) == (1, 2)


def test_inject_session_patches_and_restores_all_sites():
    import products.tasks.backend.facade.agents as facade_agents  # noqa: PLC0415
    import products.signals.backend.custom_agent.base as ca_base  # noqa: PLC0415
    import products.tasks.backend.logic.repo_selection.agent as rs_agent  # noqa: PLC0415

    original_facade = facade_agents.MultiTurnSession
    original_base = ca_base.MultiTurnSession
    original_rs = rs_agent.MultiTurnSession

    class _Sentinel:
        pass

    with inject_session(_Sentinel):
        assert facade_agents.MultiTurnSession is _Sentinel
        assert ca_base.MultiTurnSession is _Sentinel
        assert rs_agent.MultiTurnSession is _Sentinel

    assert facade_agents.MultiTurnSession is original_facade
    assert ca_base.MultiTurnSession is original_base
    assert rs_agent.MultiTurnSession is original_rs
