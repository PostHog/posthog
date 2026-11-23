"""Attribution for artefact writes — who (or what) produced a row.

Kept in its own lightweight leaf without Django or pydantic so artefact-store consumers can
import it without dragging in the models module. Re-exported from `models.py` for existing importers.
"""

from __future__ import annotations

from dataclasses import field
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
    # The authenticated principal, including when their external agent acts.
    user_id: int | None = None
    # Internal agents are attributed to their PostHog task.
    task_id: str | None = None
    # The external coding client, such as Codex, paired with its user principal.
    agent_name: str | None = None
    # The authenticated principal of the request that named this task. Not stored: the task id header is
    # caller-supplied, so claim checks need to know who sent it.
    request_user_id: int | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.kind != "task" and self.request_user_id is not None:
            raise ValueError("Only a task attribution carries a request principal")
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
    def from_task(cls, task_id: str, *, request_user_id: int | None = None) -> ArtefactAttribution:
        return cls(kind="task", task_id=str(task_id), request_user_id=request_user_id)

    @classmethod
    def from_agent(cls, user_id: int, agent_name: str) -> ArtefactAttribution:
        return cls(kind="agent", user_id=user_id, agent_name=agent_name)

    @classmethod
    def system(cls) -> ArtefactAttribution:
        return cls(kind="system")
