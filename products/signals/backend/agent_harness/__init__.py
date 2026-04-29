"""Headless Signals agent harness.

Spawns sandbox agents on a stagger schedule, persists run rows, and emits
signals via `emit_signal()`.
"""

from products.signals.backend.agent_harness.budgets import DEFAULT_BUDGET, BudgetCaps, resolve_budget
from products.signals.backend.agent_harness.skill_loader import LoadedSkill, SkillNotFoundError, load_skill_for_run

__all__ = [
    "DEFAULT_BUDGET",
    "BudgetCaps",
    "LoadedSkill",
    "SkillNotFoundError",
    "load_skill_for_run",
    "resolve_budget",
]
