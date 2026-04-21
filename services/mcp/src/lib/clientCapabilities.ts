/**
 * MCP clients known NOT to make newly-enabled tools callable after
 * `notifications/tools/list_changed`.
 *
 * "Unsupported" here is a practical behavioral test: does a tool that wasn't in the
 * initial `tools/list` become callable mid-session once the server emits `list_changed`?
 * The raw MCP SDK does handle this, but some clients wrap the SDK with their own
 * deferred/cached tool layer that doesn't re-scan on notifications.
 *
 * For these clients we surface a `_reconnectHint` on toolset enable/disable so the model
 * can ask the user to reconnect with `?toolsets=<ids>` pre-enabled — the session
 * re-initializes and the tools appear in the catalog up front.
 *
 * Findings (2026-04):
 * - **claude-code**: defers non-bootstrap tools at init, doesn't re-scan on list_changed.
 *   Verified empirically — `No such tool available` on post-enable invocation across
 *   Opus/Sonnet/Haiku.
 * - **cursor**, **codeium**, **windsurf**: documented in the MCP client compatibility
 *   matrix as not honoring list_changed.
 *
 * Last audited: 2026-04 against https://modelcontextprotocol.io/clients + local tests.
 */
const KNOWN_UNSUPPORTED_CLIENTS: readonly string[] = ['cursor', 'codeium', 'windsurf', 'claude-code']

export function clientSupportsListChanged(clientName?: string): boolean {
    if (!clientName) {
        return true
    }
    const normalized = clientName.trim().toLowerCase()
    return !KNOWN_UNSUPPORTED_CLIENTS.some((n) => normalized.includes(n))
}
