import datetime as dt
from dataclasses import dataclass, replace

from products.pulse.backend.models import BriefConfig

# System-level constants — not per-config tunables. These bound the Temporal workflow and its
# activities, the LLM call, and the stale-brief reaper. They live here (not scattered across
# modules) so the workflow, activities, api, and reaper all read one source of truth.

# Caps total wall-clock across Temporal retries/re-executions. Worst-case activity budget in
# temporal/workflow.py is ~18min (gather 2 attempts x 5min + synthesize 5min + mark-failed
# 3 x 1min); 20 keeps the in-workflow failure path authoritative.
WORKFLOW_EXECUTION_TIMEOUT = dt.timedelta(minutes=20)

GATHER_ACTIVITY_TIMEOUT = dt.timedelta(minutes=5)
GATHER_MAX_ATTEMPTS = 2
SYNTHESIZE_ACTIVITY_TIMEOUT = dt.timedelta(minutes=5)
# A failed synthesis is not retried: retrying double-spends LLM calls.
SYNTHESIZE_MAX_ATTEMPTS = 1
MARK_FAILED_ACTIVITY_TIMEOUT = dt.timedelta(minutes=1)
MARK_FAILED_MAX_ATTEMPTS = 3

# 5-min headroom above the 20-min WORKFLOW_EXECUTION_TIMEOUT so a brief still legitimately running
# is never reaped early, while a truly-stranded row is reconciled promptly.
STALE_AFTER = dt.timedelta(minutes=25)
# The reaper sweeps at most this many stranded rows per run; a later run drains the rest.
REAP_BATCH_CAP = 500

SYNTHESIS_MODEL = "gpt-4.1"
LLM_TIMEOUT_SECONDS = 120
# Worst case 2 attempts x 120s stays under the synthesize activity timeout.
LLM_MAX_RETRIES = 1

# Cap on items passed into synthesis — keeps the activity payload well under Temporal's ~2 MiB cap.
MAX_ITEMS = 50


@dataclass(frozen=True)
class BriefSettings:
    """Per-config tunables for gathering and synthesis. Defaults in DEFAULT_BRIEF_SETTINGS;
    a BriefConfig can override any subset via its `settings` JSON, clamped to safe ranges."""

    min_abs_change_pct: float = 20.0
    min_baseline_value: float = 10.0
    max_anchor_insights: int = 10
    fallback_dashboard_count: int = 3
    confidence_threshold: float = 0.6
    max_opportunities: int = 3

    @classmethod
    def from_config(cls, config: BriefConfig | None) -> "BriefSettings":
        """Merge a config's `settings` overrides over the defaults, clamping each to its range.
        Unknown keys and out-of-range values are ignored/clamped, never raised — gathering must
        not fail on a bad stored setting."""
        settings = (config.settings if config else None) or {}
        overrides: dict[str, float | int] = {}
        for key, lo, hi, cast in _RANGES:
            if key in settings:
                try:
                    overrides[key] = _clamp(cast(settings[key]), lo, hi)
                except (TypeError, ValueError):
                    continue
        return replace(DEFAULT_BRIEF_SETTINGS, **overrides)  # type: ignore[arg-type]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# (key, min, max, cast) — the allowed override knobs and their safe ranges. Kept in sync with
# BriefSettings fields and the API's BriefSettingsSerializer.
_RANGES: list[tuple[str, float, float, type]] = [
    ("min_abs_change_pct", 1.0, 1000.0, float),
    ("min_baseline_value", 0.0, 1_000_000.0, float),
    ("max_anchor_insights", 1, 100, int),
    ("fallback_dashboard_count", 1, 20, int),
    ("confidence_threshold", 0.0, 1.0, float),
    ("max_opportunities", 1, 20, int),
]

DEFAULT_BRIEF_SETTINGS = BriefSettings()
