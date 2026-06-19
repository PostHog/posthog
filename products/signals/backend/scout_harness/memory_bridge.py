"""Bridge between the Signals scout harness and the shared agent-memory tree.

Two responsibilities:

1. **Render** the slice of the shared memory tree a scout should open a run with —
   the top-level `project.md` and the scout's own `scouts/<skill>/scratchpad.md`.
2. **Mirror** `SignalScratchpad` writes into the memory tree so the per-scout
   scratchpad lives inside the shared file-tree memory too (read-through /
   write-through). `SignalScratchpad` stays the authoritative store for the
   harness's `remember`/`search` tools; this is purely additive.

All memory access goes through the `agent_memory` product facade — the scout
harness never touches that product's models or storage directly.
"""

from __future__ import annotations

import structlog
from asgiref.sync import async_to_sync

from products.agent_memory.backend.facade import api as memory_api

logger = structlog.get_logger(__name__)

# The single top-level project memory file every agent shares.
PROJECT_MEMORY_PATH = "project.md"

# Fallback scratchpad path for scratchpad writes that aren't pinned to a scout run
# (so we can't resolve which skill authored them).
_SHARED_SCRATCHPAD_PATH = "scouts/scratchpad.md"


def scratchpad_path(skill_name: str) -> str:
    """Path of a scout's scratchpad inside the shared memory tree.

    Mirrors the required tree layout `scouts/<skill_name>/scratchpad.md`. The skill
    name is already a slug (`signals-scout-errors`), so it's a safe path segment.
    """
    return f"scouts/{skill_name}/scratchpad.md"


async def render_run_memory(*, team_id: int, skill_name: str) -> str | None:
    """Return the markdown slice of shared memory to inject at run start.

    Reads `project.md` and the scout's scratchpad. Returns None when both are
    absent so the prompt can fall back to its "nothing recorded yet" copy. Never
    raises — a memory hiccup must not block a scout run.
    """
    sections: list[str] = []
    sections.append(await _read_optional(team_id=team_id, path=PROJECT_MEMORY_PATH, label="project.md"))
    sections.append(await _read_optional(team_id=team_id, path=scratchpad_path(skill_name), label="your scratchpad"))
    rendered = [s for s in sections if s]
    return "\n\n".join(rendered) if rendered else None


async def _read_optional(*, team_id: int, path: str, label: str) -> str:
    try:
        memory_file = await memory_api.aread_memory(team_id=team_id, path=path)
    except memory_api.MemoryFileNotFoundError:
        return ""
    except Exception:
        logger.exception("signals_scout.memory_read_failed", team_id=team_id, path=path)
        return ""
    return f"## `{path}` ({label})\n\n{memory_file.content.strip()}"


def mirror_scratchpad_to_memory(*, team_id: int, run_id: str | None, key: str, content: str) -> None:
    """Sync write-through of a `SignalScratchpad` entry into the shared memory tree.

    Resolves the authoring scout's `skill_name` from `run_id` to target the
    per-scout `scouts/<skill>/scratchpad.md` file; falls back to a shared
    `scouts/scratchpad.md` when the write isn't pinned to a run. The entry's `key`
    becomes a markdown section heading, upserted via `append_section` so it never
    clobbers other keys. Best-effort — a mirror failure must not fail the
    authoritative `remember` write that already succeeded.
    """
    path = _resolve_scratchpad_path(team_id=team_id, run_id=run_id)
    try:
        async_to_sync(memory_api.aappend_section)(
            team_id=team_id,
            path=path,
            heading=key,
            body=content,
            updated_by_run=run_id,
        )
    except Exception:
        logger.exception("signals_scout.scratchpad_mirror_failed", team_id=team_id, path=path, key=key)


def _resolve_scratchpad_path(*, team_id: int, run_id: str | None) -> str:
    if run_id is None:
        return _SHARED_SCRATCHPAD_PATH
    # Deferred to avoid importing the signals model layer at module import time
    # (the harness package is imported on paths that don't need the ORM).
    from products.signals.backend.models import SignalScoutRun  # noqa: PLC0415

    skill_name = SignalScoutRun.objects.filter(id=run_id, team_id=team_id).values_list("skill_name", flat=True).first()
    return scratchpad_path(skill_name) if skill_name else _SHARED_SCRATCHPAD_PATH
