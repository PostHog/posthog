"""Cassettes: recorded agent turns for deterministic replay.

A cassette captures the ordered end-turn texts an agent produced during a single
task run. Replaying a cassette feeds those exact texts back through the *real*
signals step functions — the real prompt construction, the real
``MultiTurnSession._parse_and_validate`` (JSON extraction + Pydantic validation),
and the real result-collapsing logic all run — but with no sandbox, no Temporal,
no S3, and no LLM. That makes the orchestration logic deterministically testable
and lets a fixed set of agent outputs be re-scored reproducibly in CI.

A cassette is a single JSON file so it diffs cleanly in review. Recording is done
by :class:`~products.signals.eval.agentic.session_backends.RecordingMultiTurnSession`
against a live run; replay is done by
:class:`~products.signals.eval.agentic.session_backends.ReplayMultiTurnSession`.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path

CASSETTE_SCHEMA_VERSION = 1


def prompt_fingerprint(prompt: str) -> str:
    """Stable short fingerprint of a prompt, used for drift detection on replay."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


@dataclass
class RecordedTurn:
    """One agent turn: the raw end-turn text and what it was expected to validate as.

    ``raw_text`` is exactly what the agent returned (JSON, or JSON embedded in prose) —
    replay runs the production extractor/validator over it, so a cassette that no longer
    validates against the current schema is a real, catchable regression.
    """

    index: int
    label: str
    model: str
    raw_text: str
    prompt_sha: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> RecordedTurn:
        return cls(
            index=int(data["index"]),
            label=str(data.get("label", "")),
            model=str(data.get("model", "")),
            raw_text=str(data["raw_text"]),
            prompt_sha=data.get("prompt_sha"),
        )


@dataclass
class Cassette:
    """An ordered recording of the agent turns for one task run."""

    case_id: str
    step: str
    turns: list[RecordedTurn] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    version: int = CASSETTE_SCHEMA_VERSION

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "case_id": self.case_id,
            "step": self.step,
            "meta": self.meta,
            "turns": [asdict(turn) for turn in self.turns],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Cassette:
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            case_id=str(data["case_id"]),
            step=str(data["step"]),
            turns=[RecordedTurn.from_dict(t) for t in data.get("turns", [])],
            meta=data.get("meta", {}),
            version=int(data.get("version", CASSETTE_SCHEMA_VERSION)),
        )


class CassetteExhaustedError(RuntimeError):
    """Raised when replay asks for more turns than the cassette recorded.

    Almost always means the step's turn sequence changed (e.g. a new follow-up was
    added) and the cassette needs re-recording.
    """


class TurnCursor:
    """Yields a cassette's turns in order, with a clear error when it runs dry."""

    def __init__(self, cassette: Cassette):
        self._cassette = cassette
        self._pos = 0

    def next(self, *, label: str, model: str) -> RecordedTurn:
        if self._pos >= len(self._cassette.turns):
            raise CassetteExhaustedError(
                f"cassette {self._cassette.case_id!r} ({self._cassette.step}) has "
                f"{len(self._cassette.turns)} turns but turn #{self._pos + 1} was requested "
                f"(label={label!r}, model={model!r}) — re-record the cassette"
            )
        turn = self._cassette.turns[self._pos]
        self._pos += 1
        return turn

    @property
    def consumed(self) -> int:
        return self._pos

    @property
    def total(self) -> int:
        return len(self._cassette.turns)
