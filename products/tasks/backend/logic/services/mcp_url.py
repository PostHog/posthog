from urllib.parse import urlparse

LOCAL_HOSTNAMES = ("localhost", "127.0.0.1")


def resolve_mcp_url(*, sandbox_mcp_url: str | None, mcp_server_url: str | None) -> str | None:
    if sandbox_mcp_url:
        return sandbox_mcp_url
    if not mcp_server_url:
        return None

    parsed = urlparse(mcp_server_url)
    if parsed.hostname in LOCAL_HOSTNAMES:
        # A local sandbox runs in Docker, where localhost is the container and not the host.
        port = f":{parsed.port}" if parsed.port else ""
        return parsed._replace(netloc=f"host.docker.internal{port}").geturl()
    return mcp_server_url
