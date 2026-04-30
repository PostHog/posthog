"""Headless Signals agent harness.

Spawns sandbox agents on a stagger schedule, persists run rows, and emits
signals via `emit_signal()`.
"""

from products.signals.backend.agent_harness.budgets import DEFAULT_BUDGET, BudgetCaps, resolve_budget
from products.signals.backend.agent_harness.lazy_seed import (
    CanonicalSkill,
    CanonicalSkillFile,
    CanonicalSkillParseError,
    SeedResult,
    discover_canonical_skills,
    seed_canonical_skills,
)
from products.signals.backend.agent_harness.skill_loader import LoadedSkill, SkillNotFoundError, load_skill_for_run
from products.signals.backend.agent_harness.tool_registry import (
    HARNESS_INTERNAL_TOOLS,
    AllowedToolsResolution,
    EffectiveToolset,
    InvalidAllowedToolsError,
    UnknownHarnessToolError,
    compute_effective_toolset,
    validate_and_partition_allowed_tools,
)

__all__ = [
    "AllowedToolsResolution",
    "BudgetCaps",
    "CanonicalSkill",
    "CanonicalSkillFile",
    "CanonicalSkillParseError",
    "DEFAULT_BUDGET",
    "EffectiveToolset",
    "HARNESS_INTERNAL_TOOLS",
    "InvalidAllowedToolsError",
    "LoadedSkill",
    "SeedResult",
    "SkillNotFoundError",
    "UnknownHarnessToolError",
    "compute_effective_toolset",
    "discover_canonical_skills",
    "load_skill_for_run",
    "resolve_budget",
    "seed_canonical_skills",
    "validate_and_partition_allowed_tools",
]
