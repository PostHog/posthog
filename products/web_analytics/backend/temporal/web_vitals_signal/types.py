"""
Shared types for the web-vitals signal Temporal pipeline.

These dataclasses cross the workflow ↔ activity boundary, so they must be JSON-
serializable. Keep them flat and primitive-typed.
"""

import dataclasses
from datetime import datetime


@dataclasses.dataclass(frozen=True)
class WebVitalsBucket:
    """One percentile observation for a (route, device_class) over a window."""

    route: str
    device_class: str
    p75_value: float
    sample_count: int


@dataclasses.dataclass(frozen=True)
class WebVitalsEvaluationInput:
    """Input to per-team evaluation activities. `now_iso` is the wall-clock anchor for
    the evaluation window — passed explicitly so workflow replays compute the same window
    as the original run (Temporal determinism)."""

    team_id: int
    now_iso: str

    @property
    def now(self) -> datetime:
        return datetime.fromisoformat(self.now_iso)


@dataclasses.dataclass(frozen=True)
class WebVitalsEvaluationResult:
    """Per-team evaluation summary, returned from activities to the workflow."""

    team_id: int
    metric_window_buckets_evaluated: int
    signals_emitted: int
    signals_dropped: int


@dataclasses.dataclass(frozen=True)
class WebVitalsFanOutInput:
    """Top-level workflow input. `team_ids` is optional — when omitted, the workflow
    looks up opted-in teams via an activity. Passing `team_ids` is the test/debug path."""

    team_ids: list[int] | None = None
    max_concurrent: int = 8
    # ISO timestamp. Test/debug path; production scheduler omits and the activity uses now().
    now_iso: str | None = None
