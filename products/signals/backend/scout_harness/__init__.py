"""Headless Signals agent harness.

Spawns sandbox agents from an hourly Temporal coordinator, persists run rows,
and emits signals via `emit_signal()`.
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


def __getattr__(name: str) -> object:
    # Offline environment packing imports schemas from this package before Django is configured.
    if name not in __all__:
        raise AttributeError(name)
    module = "skill_loader" if name in {"LoadedSkill", "SkillNotFoundError", "load_skill_for_run"} else "lazy_seed"
    value: object = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value
