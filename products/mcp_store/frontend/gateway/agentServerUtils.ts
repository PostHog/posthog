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

/**
 * The members whose team shares an ownerless agent run mounts for one server, one entry per
 * member. Mirrors the run-path health filter: a share drops out when the gateway cannot reach
 * it or its credential is not ready. With no credential owner the run gets every survivor.
 */
export function mountedTeamShareMembers(
    servers: readonly MCPServiceAccountServerApi[],
    serverId: string
): UserBasicApi[] {
    const byMember = new Map<number, UserBasicApi>()
    for (const server of servers) {
        if (
            server.id === serverId &&
            server.scope === 'team' &&
            server.reachable &&
            server.connection_state === 'ready'
        ) {
            byMember.set(server.shared_by.id, server.shared_by)
        }
    }
    return [...byMember.values()]
}

/** The first member by name, or email when the profile has none, with the rest folded into a count. */
export function memberNames(users: readonly UserBasicApi[]): string {
    const [first, ...rest] = users
    const name = fullName(first) || first.email
    if (rest.length === 0) {
        return name
    }
    return `${name} and ${rest.length} other${rest.length === 1 ? '' : 's'}`
}

function joinNames(names: readonly string[]): string {
    if (names.length <= 2) {
        return names.join(' and ')
    }
    return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`
}

export interface MountedConnectionsNote {
    text: string
    /** False when no share is ready, so runs cannot use the server until someone reconnects. */
    ready: boolean
}

/**
 * Whose connections a task run rides for a server. Every ready team share mounts as its own
 * server, so each member is named rather than counted, and the viewer reads as "you".
 */
export function mountedConnectionsNote(
    members: readonly UserBasicApi[],
    currentUserId: number | null
): MountedConnectionsNote {
    if (members.length === 0) {
        return { text: "No shared connection is ready, so task runs can't use this server.", ready: false }
    }
    const you = members.some((member) => member.id === currentUserId)
    const others = members
        .filter((member) => member.id !== currentUserId)
        .map((member) => fullName(member) || member.email)
    const names = joinNames(you ? ['you', ...others] : others)
    if (members.length === 1) {
        return { text: `Shared by ${names}`, ready: true }
    }
    return { text: `Shared by ${names}. Task runs get each connection as a separate server.`, ready: true }
}
