"""Swappable ``MultiTurnSession`` backends and the injection context manager.

Every agentic step drives the LLM through ``MultiTurnSession`` (the tasks facade). That
single seam is where this framework swaps behaviour without touching any production step
logic:

- **Live** — the real ``MultiTurnSession``: spins a sandbox agent against the LLM gateway.
  Used unchanged (no class here); requires the local stack + Docker (``SANDBOX_PROVIDER=docker``).
- **Recording** — :class:`RecordingMultiTurnSession` wraps Live and captures every turn's
  raw end-turn text into a :class:`~products.signals.eval.agentic.cassette.Cassette`.
- **Replay** — :class:`ReplayMultiTurnSession` reads a cassette and returns the recorded
  raw text per turn, running it through the *real* ``_parse_and_validate`` and the real
  step result-collapsing logic. No stack, no LLM, fully deterministic.

:func:`inject_session` patches the class at every bind site so the chosen backend is what
the step functions call. :func:`active_cassette` / :func:`active_recorder` carry the
per-run cassette/recorder via context vars so concurrent cases stay isolated.
"""

from __future__ import annotations

import uuid
import logging
import contextvars
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

from products.signals.eval.agentic.cassette import Cassette, RecordedTurn, TurnCursor

# Import the real session via the tasks facade (the documented cross-product surface). We keep
# this module-level reference to the genuine class so replay reuses its real `_parse_and_validate`
# even while `inject_session` patches the facade's bound name to a backend.
from products.tasks.backend.facade.agents import MultiTurnSession

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

logger = logging.getLogger(__name__)

_ModelT = TypeVar("_ModelT", bound=BaseModel)

# The bind sites where ``MultiTurnSession`` is referenced. Research imports it lazily from the
# facade at call time; the other two bind it at module import. Patching all of them (plus the
# source) makes the swap total regardless of import style.
_PATCH_TARGETS: tuple[tuple[str, str], ...] = (
    ("products.tasks.backend.logic.services.custom_prompt_multi_turn_runner", "MultiTurnSession"),
    ("products.tasks.backend.facade.agents", "MultiTurnSession"),
    ("products.signals.backend.custom_agent.base", "MultiTurnSession"),
    ("products.tasks.backend.logic.repo_selection.agent", "MultiTurnSession"),
)

_active_cursor: contextvars.ContextVar[TurnCursor | None] = contextvars.ContextVar("signals_eval_cursor", default=None)
_active_recorder: contextvars.ContextVar[_Recorder | None] = contextvars.ContextVar(
    "signals_eval_recorder", default=None
)


@dataclass
class _FakeRef:
    """Stand-in for a ``Task`` / ``TaskRun`` row: replay only ever reads ``.id``."""

    id: str


@contextmanager
def inject_session(session_cls: type) -> Iterator[None]:
    """Patch ``MultiTurnSession`` at every bind site to ``session_cls`` for the block."""
    import importlib  # noqa: PLC0415 — only needed for the patch swap

    originals: list[tuple[Any, str, Any]] = []
    for module_path, attr in _PATCH_TARGETS:
        try:
            module = importlib.import_module(module_path)
        except Exception:  # pragma: no cover - a bind site that isn't importable is simply skipped
            logger.debug("inject_session: skipping unimportable target %s", module_path)
            continue
        if hasattr(module, attr):
            originals.append((module, attr, getattr(module, attr)))
            setattr(module, attr, session_cls)
    try:
        yield
    finally:
        for module, attr, original in originals:
            setattr(module, attr, original)


# ── Replay ───────────────────────────────────────────────────────────────────────


@contextmanager
def active_cassette(cassette: Cassette) -> Iterator[TurnCursor]:
    """Bind ``cassette`` as the replay source for the block (one cursor per run)."""
    cursor = TurnCursor(cassette)
    token = _active_cursor.set(cursor)
    try:
        yield cursor
    finally:
        _active_cursor.reset(token)


def _require_cursor() -> TurnCursor:
    cursor = _active_cursor.get()
    if cursor is None:
        raise RuntimeError(
            "ReplayMultiTurnSession used with no active cassette — wrap the step call in active_cassette(...)"
        )
    return cursor


class ReplayMultiTurnSession:
    """A ``MultiTurnSession``-compatible session that replays recorded turns.

    Duck-typed to the real session's public surface (``start`` / ``start_raw`` /
    ``send_followup`` / ``send_followup_raw`` / ``end`` and the ``task`` / ``task_run``
    refs). It reuses the real ``MultiTurnSession._parse_and_validate`` so JSON extraction
    and Pydantic validation are exactly the production path — a cassette that no longer
    validates is a genuine regression, not a framework artifact.
    """

    def __init__(self, cursor: TurnCursor):
        self._cursor = cursor
        # Deterministic ids so research_task_id / repo selection task_id are stable across runs.
        self.task = _FakeRef(id=str(uuid.uuid5(uuid.NAMESPACE_URL, "signals-eval-task")))
        self.task_run = _FakeRef(id=str(uuid.uuid5(uuid.NAMESPACE_URL, "signals-eval-task-run")))

    @classmethod
    async def start(
        cls,
        prompt: str,
        context: CustomPromptSandboxContext,
        model: type[_ModelT],
        *,
        on_task_run_created: Callable[[Any], Awaitable[None]] | None = None,
        fallback_from_text: Callable[[str], _ModelT] | None = None,
        **_: Any,
    ) -> tuple[ReplayMultiTurnSession, _ModelT]:
        session = cls(_require_cursor())
        if on_task_run_created is not None:
            await on_task_run_created(session.task_run)
        turn = session._cursor.next(label="initial turn", model=model.__name__)
        try:
            parsed = MultiTurnSession._parse_and_validate(turn.raw_text, model, "initial turn")
        except Exception:
            if fallback_from_text is not None:
                return session, fallback_from_text(turn.raw_text)
            raise
        return session, parsed

    @classmethod
    async def start_raw(
        cls,
        prompt: str,
        context: CustomPromptSandboxContext,
        *,
        on_task_run_created: Callable[[Any], Awaitable[None]] | None = None,
        **_: Any,
    ) -> tuple[ReplayMultiTurnSession, str]:
        session = cls(_require_cursor())
        if on_task_run_created is not None:
            await on_task_run_created(session.task_run)
        turn = session._cursor.next(label="initial turn", model="raw")
        return session, turn.raw_text

    async def send_followup(self, message: str, model: type[_ModelT], *, label: str = "") -> _ModelT:
        turn = self._cursor.next(label=label or "followup", model=model.__name__)
        return MultiTurnSession._parse_and_validate(turn.raw_text, model, label or "followup")

    async def send_followup_raw(self, message: str, *, label: str = "") -> str:
        turn = self._cursor.next(label=label or "followup", model="raw")
        return turn.raw_text

    async def end(self, *, status: str = "completed", error: str | None = None) -> None:
        return None


# ── Recording ──────────────────────────────────────────────────────────────────────


@dataclass
class _Recorder:
    case_id: str
    step: str
    turns: list[RecordedTurn]

    def append(self, *, label: str, model: str, raw_text: str) -> None:
        self.turns.append(RecordedTurn(index=len(self.turns), label=label, model=model, raw_text=raw_text))


@contextmanager
def active_recorder(case_id: str, step: str) -> Iterator[_Recorder]:
    """Capture turns produced during the block into a recorder, retrievable as a cassette."""
    recorder = _Recorder(case_id=case_id, step=step, turns=[])
    token = _active_recorder.set(recorder)
    try:
        yield recorder
    finally:
        _active_recorder.reset(token)


def recorder_to_cassette(recorder: _Recorder, *, meta: dict | None = None) -> Cassette:
    return Cassette(case_id=recorder.case_id, step=recorder.step, turns=list(recorder.turns), meta=meta or {})


class RecordingMultiTurnSession(MultiTurnSession):
    """Live session that also records each turn's raw text into the active recorder.

    Hooks ``_parse_and_validate`` (which both ``start`` and ``send_followup`` route through,
    and which receives the turn ``label`` and target ``model``) and the raw entry points used
    by custom agents. Everything else is the real live behaviour, so a recording run is a real
    sandbox run that happens to leave a replayable cassette behind.
    """

    @staticmethod
    def _parse_and_validate(text: str, model: type[_ModelT], label: str) -> _ModelT:
        recorder = _active_recorder.get()
        if recorder is not None:
            recorder.append(label=label, model=model.__name__, raw_text=text)
        return MultiTurnSession._parse_and_validate(text, model, label)

    @classmethod
    async def start_raw(cls, prompt: str, context: CustomPromptSandboxContext, **kwargs: Any):
        session, raw = await super().start_raw(prompt, context, **kwargs)
        recorder = _active_recorder.get()
        if recorder is not None:
            recorder.append(label="initial turn (raw)", model="raw", raw_text=raw)
        return session, raw

    async def send_followup_raw(self, message: str, *, label: str = "") -> str:
        raw = await super().send_followup_raw(message, label=label)
        recorder = _active_recorder.get()
        if recorder is not None:
            recorder.append(label=label or "followup (raw)", model="raw", raw_text=raw)
        return raw
