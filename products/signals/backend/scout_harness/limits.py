from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

# Run limits are static harness defaults — per-team `limit_overrides` was dropped
# in PR 2 review as a config knob nobody asked for. Callers (management command,
# coordinator) can still pass a transient overrides dict for ad-hoc runs.
#
# `max_runtime_s` is the hard cap on the sandbox poll loop; the poll-loop's own
# timeout kills runaway agents. Lowering it below the poll cap shortens the run,
# raising it above the poll cap has no effect (the poll loop wins).
#
# `max_findings` is a soft target — the agent self-limits via the
# `signals-scout-runs-findings-create` idempotency rule plus its own
# "fewer, better" calibration. We don't reject finding emits past the cap;
# downstream queries can count emitted `Signal` rows linked via `task_run_id`.
DEFAULT_MAX_RUNTIME_S = 30 * 60  # 30 minutes — must match `MAX_POLL_SECONDS` in the sandbox runner.
DEFAULT_MAX_FINDINGS = 5


@dataclass(frozen=True)
class RunLimits:
    """Per-run upper bounds for things with a real source + enforcement path.

    Cost and tool-call caps are deliberately *not* in here — token cost data only
    arrives via LLM analytics (joined via `SignalScoutRun.task_run` → `task_run.id`
    later) and there's no runtime enforcement primitive for either today. Adding
    fields without a populate path would make the schema lie about what we
    measure; keeping this dataclass honest is the priority.
    """

    max_runtime_s: int = DEFAULT_MAX_RUNTIME_S
    max_findings: int = DEFAULT_MAX_FINDINGS

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_LIMITS = RunLimits()


def resolve_limits(overrides: dict[str, Any] | None) -> RunLimits:
    """Apply a partial overrides dict on top of `DEFAULT_LIMITS`.

    Unknown keys are ignored so a stale override doesn't crash the runner during a
    schema bump. Type coercion is intentionally minimal — feed in clean values
    from the config layer.
    """
    if not overrides:
        return DEFAULT_LIMITS
    known: dict[str, Any] = {
        field: overrides[field] for field in ("max_runtime_s", "max_findings") if field in overrides
    }
    return replace(DEFAULT_LIMITS, **known) if known else DEFAULT_LIMITS
