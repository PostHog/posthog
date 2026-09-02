"""Attribution for artefact writes — who (or what) produced a row.

Kept in its own lightweight leaf without Django or pydantic so artefact-store consumers can
import it without dragging in the models module. Re-exported from `models.py` for existing importers.
"""

from __future__ import annotations

from typing import Literal

from posthog.dataclasses import frozen


@frozen
class ArtefactAttribution:
    """Who or what produced an artefact.

    Required on every artefact write helper so no write site can silently skip attribution:
    callers must consciously pick a constructor. An external agent keeps both the authenticated
    user principal and the MCP client name, while an internal task uses only its task id.
    """

    kind: Literal["user", "task", "agent", "system"]
    user_id: int | None = None
    task_id: str | None = None
    agent_name: str | None = None

    def __post_init__(self) -> None:
        match self.kind:
            case "user":
                valid = self.user_id is not None and self.task_id is None and self.agent_name is None
            case "task":
                valid = self.task_id is not None and self.user_id is None and self.agent_name is None
            case "agent":
                valid = self.user_id is not None and self.task_id is None and bool(self.agent_name)
            case _:
                valid = self.user_id is None and self.task_id is None and self.agent_name is None
        if not valid:
            raise ValueError(f"ArtefactAttribution kind {self.kind!r} does not match its id fields")

    @classmethod
    def from_user(cls, user_id: int) -> ArtefactAttribution:
        return cls(kind="user", user_id=user_id)

    @classmethod
    def from_task(cls, task_id: str) -> ArtefactAttribution:
        return cls(kind="task", task_id=str(task_id))

    @classmethod
    def from_agent(cls, user_id: int, agent_name: str) -> ArtefactAttribution:
        return cls(kind="agent", user_id=user_id, agent_name=agent_name)

    @classmethod
    def system(cls) -> ArtefactAttribution:
        return cls(kind="system")
