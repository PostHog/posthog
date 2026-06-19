"""Headless Signals agent harness.

Spawns sandbox agents from an hourly Temporal coordinator, persists run rows,
and emits signals via `emit_signal()`.
"""

from products.signals.backend.scout_harness.lazy_seed import (
    CanonicalSkill,
    CanonicalSkillFile,
    CanonicalSkillParseError,
    SeedResult,
    SyncResult,
    discover_canonical_skills,
    seed_canonical_skills,
    sync_canonical_skills,
)
from products.signals.backend.scout_harness.skill_loader import LoadedSkill, SkillNotFoundError, load_skill_for_run

__all__ = [
    "CanonicalSkill",
    "CanonicalSkillFile",
    "CanonicalSkillParseError",
    "LoadedSkill",
    "SeedResult",
    "SkillNotFoundError",
    "SyncResult",
    "discover_canonical_skills",
    "load_skill_for_run",
    "seed_canonical_skills",
    "sync_canonical_skills",
]
