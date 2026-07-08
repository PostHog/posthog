from posthog.api.routing import RouterRegistry

from products.live_debugger.backend.api import LiveDebuggerBreakpointViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(
        r"live_debugger_breakpoints",
        LiveDebuggerBreakpointViewSet,
        "project_live_debugger_breakpoints",
        ["project_id"],
    )
