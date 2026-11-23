from posthog.event_usage import EventSource

from products.warehouse_sources.backend.facade.types import DataWarehouseTableCreatedVia

# Which request surface each transport attributes a table to. The PostHog apps and the headless
# agents share `self_driving`, matching how the source path collapses them. Agent transports that
# wrap MCP but aren't separately tracked (the CLI, Slack, Max, WebMCP) land on `mcp` alongside plain MCP
# clients, and anything without a surface of its own is a plain API caller.
_EVENT_SOURCE_TO_CREATED_VIA: dict[str, DataWarehouseTableCreatedVia] = {
    EventSource.WEB: DataWarehouseTableCreatedVia.WEB,
    EventSource.WIZARD: DataWarehouseTableCreatedVia.WIZARD,
    EventSource.POSTHOG_CODE: DataWarehouseTableCreatedVia.SELF_DRIVING,
    EventSource.DESKTOP: DataWarehouseTableCreatedVia.SELF_DRIVING,
    EventSource.MOBILE: DataWarehouseTableCreatedVia.SELF_DRIVING,
    EventSource.MCP: DataWarehouseTableCreatedVia.MCP,
    EventSource.SLACK: DataWarehouseTableCreatedVia.MCP,
    EventSource.CLI: DataWarehouseTableCreatedVia.MCP,
    EventSource.POSTHOG_AI: DataWarehouseTableCreatedVia.MCP,
    EventSource.WEBMCP: DataWarehouseTableCreatedVia.MCP,
}


def table_created_via(event_source: str, is_self_driving_wizard: bool) -> str:
    created_via = _EVENT_SOURCE_TO_CREATED_VIA.get(event_source, DataWarehouseTableCreatedVia.API)
    if created_via == DataWarehouseTableCreatedVia.WIZARD and is_self_driving_wizard:
        return DataWarehouseTableCreatedVia.SELF_DRIVING
    return created_via
