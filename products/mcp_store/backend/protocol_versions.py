# MCP protocol versions the store's client offers to upstream servers, newest first.
# 2025-11-25 is left out because it lets a server drop an SSE response stream and expect
# the client to resume it with a GET request, which this client does not do.
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = ("2025-06-18", "2025-03-26", "2024-11-05")

LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
