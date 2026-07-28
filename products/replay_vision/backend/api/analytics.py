from rest_framework.request import Request

from posthog.event_usage import EventSource, get_event_source


def event_source(request: Request) -> str:
    """Surface tag for Replay Vision product events, so one server-side capture path
    distinguishes UI from MCP (and other API) callers. Derived from the request rather
    than the authenticator directly: `get_event_source` reads the MCP client headers the
    MCP server sets, which is more precise than "was this a personal API key" (scripts use
    those too). The in-app UI resolves to `ui`; everything else keeps its source value."""
    source = get_event_source(request)
    return "ui" if source == EventSource.WEB else str(source)
