/**
 * MCP clients known NOT to refresh their tool list on `notifications/tools/list_changed`.
 *
 * When `toolsets(action='enable'|'disable')` runs in progressive mode for one of these
 * clients, we fall back to instructing the model (via appended text) to ask the user to
 * reconnect with `?toolsets=<ids>`, which re-initializes the session with those toolsets
 * already active.
 *
 * Maintained conservatively: when in doubt, assume the client DOES support list_changed
 * and rely on the notification. The `note` field in the tool response already tells the
 * model how to recover, so this secondary hint is belt-and-suspenders for clients where
 * we've empirically confirmed the auto-refresh is broken.
 *
 * Last audited: 2026-04 against https://modelcontextprotocol.io/clients
 */
const KNOWN_UNSUPPORTED_CLIENTS: readonly string[] = ['cursor', 'codeium', 'windsurf']

export function clientSupportsListChanged(clientName?: string): boolean {
    if (!clientName) {
        return true
    }
    const normalized = clientName.trim().toLowerCase()
    return !KNOWN_UNSUPPORTED_CLIENTS.some((n) => normalized.includes(n))
}
