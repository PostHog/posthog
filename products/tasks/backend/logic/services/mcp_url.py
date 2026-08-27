from urllib.parse import urlparse


def resolve_mcp_url(*, sandbox_mcp_url: str | None, site_url: str | None) -> str | None:
    if sandbox_mcp_url:
        return sandbox_mcp_url
    if not site_url:
        return None

    hostname = urlparse(site_url).hostname or ""
    if hostname in ("app.posthog.com", "us.posthog.com"):
        return "https://mcp.posthog.com/mcp"
    if hostname == "eu.posthog.com":
        return "https://mcp-eu.posthog.com/mcp"
    if hostname == "app.dev.posthog.dev":
        return "https://mcp.dev.posthog.dev/mcp"
    if hostname in ("localhost", "127.0.0.1"):
        return "http://host.docker.internal:8787/mcp"

    return None
