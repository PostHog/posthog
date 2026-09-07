from posthog.mcp import resolve_posthog_mcp_url


def resolve_mcp_url(*, sandbox_mcp_url: str | None, site_url: str | None) -> str | None:
    return resolve_posthog_mcp_url(configured_url=sandbox_mcp_url, site_url=site_url)
