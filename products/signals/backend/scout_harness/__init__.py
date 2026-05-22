"""Headless Signals agent harness.

Spawns sandbox agents from an hourly Temporal coordinator, persists run rows,
and emits signals via `emit_signal()`.
"""

from products.signals.backend.scout_harness.lazy_seed import (
    CanonicalSkill,
    CanonicalSkillFile,
    CanonicalSkillParseError,
    SeedResult,
    discover_canonical_skills,
    seed_canonical_skills,
)
from products.signals.backend.scout_harness.skill_loader import LoadedSkill, SkillNotFoundError, load_skill_for_run
from products.signals.backend.scout_harness.tool_registry import (
    HARNESS_INTERNAL_TOOLS,
    AllowedToolsResolution,
    InvalidAllowedToolsError,
    UnknownHarnessToolError,
    validate_and_partition_allowed_tools,
)

__all__ = [
    "AllowedToolsResolution",
    "CanonicalSkill",
    "CanonicalSkillFile",
    "CanonicalSkillParseError",
    "HARNESS_INTERNAL_TOOLS",
    "InvalidAllowedToolsError",
    "LoadedSkill",
    "SeedResult",
    "SkillNotFoundError",
    "UnknownHarnessToolError",
    "discover_canonical_skills",
    "load_skill_for_run",
    "seed_canonical_skills",
    "validate_and_partition_allowed_tools",
]
