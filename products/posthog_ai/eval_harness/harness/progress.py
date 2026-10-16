from __future__ import annotations

from pathlib import Path
from typing import Literal

from posthog.dataclasses import frozen

TrialPhase = Literal["queued", "setup", "agent", "cleanup", "logs", "scoring", "done", "error", "timeout", "canceled"]
TERMINAL_PHASES = {"done", "error", "timeout", "canceled"}


@frozen
class TrialProgress:
    trial_id: str
    experiment: str
    name: str
    trial_index: int
    phase: TrialPhase
    started: float
    log_dir: Path | None
    ended: float | None = None
    detail: str = ""
    retries: int = 0
