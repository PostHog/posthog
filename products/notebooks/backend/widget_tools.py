import re
import json
import asyncio
from typing import Literal
from uuid import UUID

from django.conf import settings

from asgiref.sync import async_to_sync

from posthog.mcp import resolve_notebook_widget_mcp_url
from posthog.models import OAuthAccessToken, User
from posthog.temporal.oauth import create_oauth_access_token_for_user

from products.canvas.backend import notebook_integration as canvas_facade
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.widgets import WidgetConflictError, WidgetError, _get_instance_and_version

MAX_WIDGET_TOOL_ARGUMENT_BYTES = 64 * 1024
MAX_WIDGET_TOOL_RESULT_BYTES = 1024 * 1024
WIDGET_TOOL_TIMEOUT_SECONDS = 30
_TOOL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")


async def _execute_mcp_command(*, url: str, headers: dict[str, str], team_id: int, command: str) -> str:
    from ee.hogai.tools.call_mcp_server.mcp_client import (  # noqa: PLC0415 — keeps the MCP SDK off Django startup
        MCPClient,
        MCPClientError,
    )

    client = MCPClient(url, headers=headers, team_id=team_id)
    try:
        async with asyncio.timeout(WIDGET_TOOL_TIMEOUT_SECONDS):
            await client.initialize()
            return await client.call_tool("exec", {"command": command})
    except TimeoutError as error:
        raise WidgetError("The PostHog tool call took too long. Try again.", "tool_call_timed_out") from error
    except MCPClientError as error:
        raise WidgetError("The PostHog tool call failed. Check its input and try again.", "tool_call_failed") from error
    finally:
        await client.close()


def execute_posthog_mcp_command(
    *, user: User, team_id: int, command: str, scopes: Literal["read_only", "full"] = "full"
) -> str:
    url = resolve_notebook_widget_mcp_url(site_url=settings.SITE_URL)
    if url is None:
        raise WidgetError("PostHog tools are unavailable on this instance.", "tools_unavailable")
    token = create_oauth_access_token_for_user(
        user,
        team_id,
        scopes=scopes,
        include_internal_scopes=False,
    )
    try:
        result = async_to_sync(_execute_mcp_command)(
            url=url,
            team_id=team_id,
            command=command,
            headers={
                "Authorization": f"Bearer {token}",
                "x-posthog-project-id": str(team_id),
                "x-posthog-mcp-version": "2",
                "x-posthog-read-only": "true" if scopes == "read_only" else "false",
                "x-posthog-mcp-consumer": "posthog-ai",
            },
        )
    finally:
        OAuthAccessToken.objects.filter(token=token).delete()
    if len(result.encode()) > MAX_WIDGET_TOOL_RESULT_BYTES:
        raise WidgetError("The PostHog tool returned too much data for this widget.", "tool_result_too_large")
    return result


def call_widget_tool(
    *,
    notebook: Notebook,
    node_id: str,
    version_id: UUID,
    build_hash: str,
    user: User,
    tool_name: str,
    arguments: dict[str, object],
) -> str:
    _instance, version = _get_instance_and_version(notebook, node_id, version_id)
    if not version.tool_access:
        raise WidgetError("This widget version cannot call PostHog tools.", "tool_not_allowed")
    try:
        canvas_versions = canvas_facade.list_notebook_canvas_versions(
            team_id=notebook.team_id,
            canvas_id=version.widget.canvas_id,
            version_ids=[version.canvas_source_version_id],
        )
    except canvas_facade.NotebookCanvasError as error:
        raise WidgetConflictError(
            "This tool request does not match the verified widget build.", "artifact_mismatch"
        ) from error
    if len(canvas_versions) != 1 or canvas_versions[0].build_hash != build_hash:
        raise WidgetConflictError("This tool request does not match the verified widget build.", "artifact_mismatch")
    if not _TOOL_NAME.fullmatch(tool_name):
        raise WidgetError("This PostHog tool name is invalid.", "invalid_tool_name")
    encoded_arguments = json.dumps(arguments, separators=(",", ":"))
    if len(encoded_arguments.encode()) > MAX_WIDGET_TOOL_ARGUMENT_BYTES:
        raise WidgetError("The PostHog tool input is too large.", "tool_input_too_large")
    return execute_posthog_mcp_command(
        user=user,
        team_id=notebook.team_id,
        command=f"call --json {tool_name} {encoded_arguments}",
    )
