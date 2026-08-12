"""Attribution for artefact writes — who (or what) produced a row.

Kept in its own stdlib-only leaf (no Django, no pydantic) so any artefact-store consumer can
import it without dragging the heavy models module. Re-exported from `models.py` for existing
importers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ArtefactAttribution:
    """Who (or what) produced an artefact — exactly one of a user, a task, or the system.

    Required on every artefact write helper so no write site can silently skip attribution:
    callers must consciously pick `from_user` / `from_task` / `system()`. System attribution
    covers pipeline writers with neither in scope (e.g. the safety judge); it stores NULLs,
    indistinguishable from legacy rows by design.
    """

    kind: Literal["user", "task", "system"]
    user_id: int | None = None
    task_id: str | None = None

    def __post_init__(self) -> None:
        match self.kind:
            case "user":
                valid = self.user_id is not None and self.task_id is None
            case "task":
                valid = self.task_id is not None and self.user_id is None
            case _:
                valid = self.user_id is None and self.task_id is None
        if not valid:
            raise ValueError(f"ArtefactAttribution kind {self.kind!r} does not match its id fields")

    @classmethod
    def from_user(cls, user_id: int) -> ArtefactAttribution:
        return cls(kind="user", user_id=user_id)

    @classmethod
    def from_task(cls, task_id: str) -> ArtefactAttribution:
        return cls(kind="task", task_id=str(task_id))

    @classmethod
    def system(cls) -> ArtefactAttribution:
        return cls(kind="system")
