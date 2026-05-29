/**
 * MSW-backing data store.
 *
 * Owns the agent-console's mocked read state — base fixtures
 * re-exported from `@posthog/agent-chat/fixtures`. App code never
 * imports from here; it goes through `apiClient` which MSW intercepts
 * in Storybook. Ripping it out means deleting `.storybook/mocks/` and
 * pointing the Next.js rewrites at the real backends.
 *
 * Writes live in Django + the agent-ingress runner — the console is
 * read-mostly, so no overlay / event emitter lives here. Refreshes
 * after agent-driven mutations happen via URL navigation + the
 * `reloadSignal` (see `src/lib/reloadSignal.ts`).
 */

import type { ChatSession } from '@posthog/agent-chat'
import {
    agents,
    agentsWithArchived,
    fleetLiveSessions,
    fleetStats,
    getAgentStatsFixture,
    listLogsForSessionFixture,
    listSessionsForAgentFixture,
    weeklyDigest,
    weeklyDigestBundle,
    weeklyDigestRevisions,
} from '@posthog/agent-chat/fixtures'
import type {
    AgentApplicationFixture,
    AgentRevisionFixture,
    AgentStats,
    FleetStats,
    LogEntry,
} from '@posthog/agent-chat/fixtures'

export function listAgentsStore(opts: { includeArchived?: boolean } = {}): AgentApplicationFixture[] {
    return opts.includeArchived ? agentsWithArchived : agents
}

export function getAgentBySlugStore(slug: string): AgentApplicationFixture | null {
    return agentsWithArchived.find((a) => a.slug === slug) ?? null
}

export function listRevisionsStore(slug: string): AgentRevisionFixture[] {
    const agent = getAgentBySlugStore(slug)
    if (!agent) {
        return []
    }
    return baseRevisionsForApplication(agent.id)
}

/**
 * Returns Django's bulk-bundle shape: `{ files: { path: content }, sha256 }`.
 * The apiClient transforms this to `BundleFile[]` on the client side.
 */
export function getBundleRawStore(
    slug: string,
    revisionId: string
): { files: Record<string, string>; sha256: string | null } {
    const agent = getAgentBySlugStore(slug)
    if (!agent) {
        return { files: {}, sha256: null }
    }
    const baseFiles = baseBundleForApplication(agent.id)
    const files: Record<string, string> = {}
    for (const file of baseFiles) {
        files[file.path] = file.content
    }
    const rev = baseRevisionsForApplication(agent.id).find((r) => r.id === revisionId)
    return { files, sha256: rev?.bundle_sha256 ?? null }
}

export function getAgentStatsStore(slug: string): AgentStats | null {
    const agent = getAgentBySlugStore(slug)
    return agent ? getAgentStatsFixture(agent.id) : null
}

export function listSessionsForAgentStore(slug: string): ChatSession[] {
    const agent = getAgentBySlugStore(slug)
    return agent ? listSessionsForAgentFixture(agent.id) : []
}

export function getSessionStore(sessionId: string): ChatSession | null {
    for (const agent of agents) {
        const found = listSessionsForAgentFixture(agent.id).find((s) => s.id === sessionId)
        if (found) {
            return found
        }
    }
    return fleetLiveSessions.find((s) => s.id === sessionId) ?? null
}

export function listLogsForSessionStore(sessionId: string): LogEntry[] {
    return listLogsForSessionFixture(sessionId)
}

export function getFleetStatsStore(): FleetStats {
    return fleetStats
}

export function listLiveSessionsStore(): ChatSession[] {
    return fleetLiveSessions
}

function baseBundleForApplication(applicationId: string): typeof weeklyDigestBundle {
    if (applicationId === weeklyDigest.id) {
        return weeklyDigestBundle
    }
    return []
}

function baseRevisionsForApplication(applicationId: string): AgentRevisionFixture[] {
    if (applicationId === weeklyDigest.id) {
        return weeklyDigestRevisions
    }
    return []
}
