import type { LemonTagType } from '@posthog/lemon-ui'

import type { MCPServiceAccountServerApi } from '../generated/api.schemas'

/**
 * The servers an agent's ownerless runs (a scout, a workflow task) can mount: reachable team-scoped
 * grants only (the gateway refuses grants on project-disabled servers and grants whose owner an admin
 * revoked), one row per server. Several members can team-share the same server and the run mounts
 * every healthy team share, so the row carries a ready share when one exists and its health tag does
 * not report a problem the run does not have. Sorted by name, ignoring case.
 */
export function teamSharedAgentServers(servers: readonly MCPServiceAccountServerApi[]): MCPServiceAccountServerApi[] {
    const byServer = new Map<string, MCPServiceAccountServerApi>()
    for (const server of servers) {
        if (server.scope !== 'team' || !server.reachable) {
            continue
        }
        const existing = byServer.get(server.id)
        if (!existing || (existing.connection_state !== 'ready' && server.connection_state === 'ready')) {
            byServer.set(server.id, server)
        }
    }
    return [...byServer.values()].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
}

/** The tag a picker row shows when the share behind a server is not ready to use. */
export function agentServerConnectionIssue(
    server: MCPServiceAccountServerApi
): { label: string; tagType: LemonTagType } | null {
    switch (server.connection_state) {
        case 'needs_reauth':
            return { label: 'Reconnect', tagType: 'danger' }
        case 'pending_oauth':
            return { label: 'Pending OAuth', tagType: 'warning' }
        case 'disabled':
            return { label: 'Disabled', tagType: 'muted' }
        case 'missing_credential':
            return { label: 'Needs connection', tagType: 'warning' }
        default:
            return null
    }
}
