"""
Facade for webmcp.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from posthog.models import User

from ..logic.mcp_server import McpServerClient, get_mcp_server_url
from . import contracts


def is_available() -> bool:
    return get_mcp_server_url() is not None


def get_exec_tool(user_id: int, team_id: int) -> contracts.ExecTool:
    return McpServerClient.for_user(User.objects.get(id=user_id), team_id).get_exec_tool()


def run_exec(input: contracts.RunExecInput) -> contracts.ExecResult:
    return McpServerClient.for_user(User.objects.get(id=input.user_id), input.team_id).call_exec(input.command)
