"""
Facade re-exports for the sandbox execution surface.

These are behavioral primitives (abstract base class + config/value types + factory
functions), not data — other products construct and drive sandboxes through them. They
cross the boundary as objects, per the wiring pattern. Kept out of ``facade/api.py`` so the
heavy docker/modal dependencies stay off the light data-surface import path.
"""

from typing import TYPE_CHECKING, Any, Protocol, cast

from products.tasks.backend.logic.services.agent_command import CommandResult, send_agent_command
from products.tasks.backend.logic.services.connection_token import (
    create_sandbox_connection_token as _create_sandbox_connection_token,
)
from products.tasks.backend.logic.services.sandbox import (
    SandboxBase,
    SandboxClass,
    SandboxConfig,
    SandboxResources,
    SandboxStatus,
    SandboxTemplate,
    get_sandbox_class,
    get_sandbox_class_for_backend,
    is_public_sandbox_repo,
)
from products.tasks.backend.temporal.process_task.utils import McpServerConfig, build_sandbox_environment_variables

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


class SandboxRunRef(Protocol):
    """Structural stand-in for a TaskRun in the sandbox command/token helpers.

    ``send_agent_command`` and ``create_sandbox_connection_token`` only read these
    attributes off the run, so callers without a TaskRun row (e.g. pulse agent runs)
    can drive a live sandbox with any object of this shape.
    """

    id: str
    task_id: str
    team_id: int
    mode: str
    state: dict[str, Any] | None


def create_sandbox_connection_token(run_ref: SandboxRunRef, user_id: int, distinct_id: str) -> str:
    """Mint the Bearer JWT the sandbox agent-server requires on its /command channel."""
    return _create_sandbox_connection_token(cast("TaskRun", run_ref), user_id, distinct_id)


__all__ = [
    "CommandResult",
    "McpServerConfig",
    "SandboxBase",
    "SandboxClass",
    "SandboxConfig",
    "SandboxResources",
    "SandboxRunRef",
    "SandboxStatus",
    "SandboxTemplate",
    "build_sandbox_environment_variables",
    "create_sandbox_connection_token",
    "get_sandbox_class",
    "get_sandbox_class_for_backend",
    "is_public_sandbox_repo",
    "send_agent_command",
]
