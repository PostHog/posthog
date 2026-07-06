"""Unit tests for cassettes, replay/recording sessions, and session injection.

Deterministic and DB-free. Run with::

    DJANGO_SETTINGS_MODULE=posthog.settings DEBUG=1 TEST=1 .venv/bin/pytest \
      products/signals/eval/agentic/ -o python_files="test_*.py" -o python_functions="test_*"
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from products.signals.eval.agentic.cassette import (
    Cassette,
    CassetteExhaustedError,
    RecordedTurn,
    TurnCursor,
    prompt_fingerprint,
)
from products.signals.eval.agentic.session_backends import ReplayMultiTurnSession, active_cassette, inject_session


class _Probe(BaseModel):
    value: int
    label: str


def _cassette(*raw_texts: str, step: str = "research") -> Cassette:
    return Cassette(
        case_id="t",
        step=step,
        turns=[RecordedTurn(index=i, label=f"turn{i}", model="_Probe", raw_text=t) for i, t in enumerate(raw_texts)],
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
