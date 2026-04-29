from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

# Defaults aligned with the spec's 30-min hard cap. Per-team overrides are stored
# on `SignalAgentConfig.budget_overrides` as a partial jsonb dict.
DEFAULT_MAX_TOOL_CALLS = 60
DEFAULT_MAX_COST_USD = 5.0
DEFAULT_MAX_RUNTIME_S = 30 * 60  # 30 minutes — must match `MAX_POLL_SECONDS` in the sandbox runner.
DEFAULT_MAX_FINDINGS = 5


@dataclass(frozen=True)
class BudgetCaps:
    """Per-run budget envelope. Enforced before tool dispatch and re-checked between steps.

    `max_runtime_s` is also the hard cap on the sandbox poll loop — the runner relies on the
    poll-loop's own timeout to kill runaway agents. Lowering it below the poll cap shortens
    the run, raising it above the poll cap has no effect (the poll loop wins).
    """

    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    max_cost_usd: float = DEFAULT_MAX_COST_USD
    max_runtime_s: int = DEFAULT_MAX_RUNTIME_S
    max_findings: int = DEFAULT_MAX_FINDINGS

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_BUDGET = BudgetCaps()


def resolve_budget(overrides: dict[str, Any] | None) -> BudgetCaps:
    """Apply a partial overrides dict on top of `DEFAULT_BUDGET`.

    Unknown keys are ignored (so we don't crash on stale overrides during a schema bump).
    Type coercion is intentionally minimal — feed in clean values from the config layer.
    """
    if not overrides:
        return DEFAULT_BUDGET
    known: dict[str, Any] = {
        field: overrides[field]
        for field in ("max_tool_calls", "max_cost_usd", "max_runtime_s", "max_findings")
        if field in overrides
    }
    return replace(DEFAULT_BUDGET, **known) if known else DEFAULT_BUDGET
