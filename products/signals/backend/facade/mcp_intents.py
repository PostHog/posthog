"""Buffer the intents that MCP agents state on API calls, for the activity summary.

`ActivityLoggingMiddleware` calls this on MCP requests, so it does no network I/O.
"""

from products.signals.backend.activity_summary import mcp_buffer


def buffer_mcp_intent(
    *, team_id: int, user_id: int, session_id: str | None, route_name: str | None, intent: str
) -> None:
    mcp_buffer.BUFFER.append(
        team_id=team_id, user_id=user_id, session_id=session_id, route_name=route_name, intent=intent
    )
