from unittest.mock import MagicMock

from products.tasks.backend.temporal.process_task.utils import McpServerConfig


def make_task_run_mock(team_id: int = 7, created_by_id: int | None = 42, state: dict | None = None) -> MagicMock:
    task = MagicMock()
    task.created_by_id = created_by_id
    if created_by_id is not None:
        task.created_by = MagicMock(id=created_by_id, distinct_id=f"user-{created_by_id}")
    else:
        task.created_by = None
    task_run = MagicMock()
    task_run.id = "run-1"
    task_run.team_id = team_id
    task_run.task = task
    task_run.task_id = "task-1"
    # Default to None so `(task_run.state or {}).get(...)` returns None cleanly.
    # MagicMock auto-attributes would otherwise return further MagicMock objects
    # and leak into kwargs passed to `get_sandbox_ph_mcp_configs`.
    task_run.state = state
    return task_run


def make_mcp_config(name: str = "posthog", token: str = "tok") -> McpServerConfig:
    return McpServerConfig(
        type="http",
        name=name,
        url="https://mcp.posthog.com/mcp",
        headers=[{"name": "Authorization", "value": f"Bearer {token}"}],
    )
