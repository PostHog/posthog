import type { LemonTagType } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils/strings'

import type { MCPServiceAccountServerApi, UserBasicApi } from '../generated/api.schemas'

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

/** The members whose reachable team shares back one server, one entry per member. */
export function teamShareMembers(servers: readonly MCPServiceAccountServerApi[], serverId: string): UserBasicApi[] {
    const byMember = new Map<number, UserBasicApi>()
    for (const server of servers) {
        if (server.id === serverId && server.scope === 'team' && server.reachable) {
            byMember.set(server.shared_by.id, server.shared_by)
        }
    }
    return [...byMember.values()]
}

function othersSuffix(count: number): string {
    if (count === 0) {
        return ''
    }
    return ` and ${count} other${count === 1 ? '' : 's'}`
}

/** The first member by name, or email when the profile has none, with the rest folded into a count. */
export function memberNames(users: readonly UserBasicApi[]): string {
    const [first, ...rest] = users
    return `${fullName(first) || first.email}${othersSuffix(rest.length)}`
}

/** Who backs a server an agent run mounts. The viewer reads their own share as "you", never as a name. */
export function sharedByLabel(members: readonly UserBasicApi[], currentUserId: number | null): string | null {
    if (members.length === 0) {
        return null
    }
    const others = members.filter((member) => member.id !== currentUserId)
    if (others.length === members.length) {
        return `Shared by ${memberNames(others)}`
    }
    return `Shared by you${othersSuffix(others.length)}`
}
