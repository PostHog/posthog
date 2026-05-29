/**
 * MSW-backing data store.
 *
 * This module owns *all* of the agent-console's mocked state:
 *   - Base fixtures (re-exported from `@posthog/agent-chat/fixtures`).
 *   - Per-entity overlays absorbed by write handlers.
 *   - The mutation event emitter consumed by the `/agent_events/stream`
 *     SSE handler.
 *
 * App code must never import from here directly — it goes through
 * `src/lib/apiClient.ts` (REST) or its `subscribeMutations` (SSE),
 * which make real HTTP requests that MSW intercepts. The point of
 * this module is that the *only* boundary between "fake data" and
 * "the app" is the network layer; ripping it out for the real backend
 * is a straightforward swap (delete `.storybook/mocks/`, point the
 * API base URL at the real ingress, done).
 *
 * v0 demo overlay shape:
 *   bundleOverlay      `${slug}:${path}` → patched content
 *   revisionSpecOverlay revisionId → shallow patch merged onto base spec
 *
 * The event emitter shape:
 *   `MutationEvent = { entityKey, mutationId, at, revision }`
 *   Entity keys are slug-based so consumers can subscribe without
 *   knowing the internal application id:
 *     bundle-file   `bundle-file:<slug>:<path>`
 *     bundle        `bundle:<slug>`
 *     revision-spec `revision-spec:<slug>:<revisionId>`
 *     revisions     `revisions:<slug>`
 *
 *   `recordMutation` cascades bundle-file → bundle and revision-spec →
 *   revisions so aggregate-view consumers (bundle tree, revisions list)
 *   refetch off one subscription.
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
    liveSessionCountsByAgent,
    weeklyDigest,
    weeklyDigestBundle,
    weeklyDigestRevisions,
} from '@posthog/agent-chat/fixtures'
import type {
    AgentApplicationFixture,
    AgentRevisionFixture,
    AgentStats,
    BundleFile,
    FleetStats,
    LogEntry,
} from '@posthog/agent-chat/fixtures'

type RevisionSpec = AgentRevisionFixture['spec']

/* ── Read paths (all slug-keyed) ─────────────────────────────────── */

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
    const base = baseRevisionsForApplication(agent.id)
    return base.map((rev) => {
        const patch = revisionSpecOverlay.get(rev.id)
        if (!patch) {
            return rev
        }
        return { ...rev, spec: { ...rev.spec, ...patch } as RevisionSpec }
    })
}

export function getBundleStore(slug: string): BundleFile[] {
    const agent = getAgentBySlugStore(slug)
    if (!agent) {
        return []
    }
    const base = baseBundleForApplication(agent.id)
    return base.map((f) => {
        const patched = bundleOverlay.get(`${slug}:${f.path}`)
        return patched !== undefined ? { ...f, content: patched } : f
    })
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

export function countLiveSessionsForAgentStore(slug: string): number {
    const agent = getAgentBySlugStore(slug)
    return agent ? (liveSessionCountsByAgent[agent.id] ?? 0) : 0
}

/* ── Write paths (slug-keyed) ────────────────────────────────────── */

const bundleOverlay = new Map<string, string>()
const revisionSpecOverlay = new Map<string, Partial<RevisionSpec>>()

export interface BundleFileWrite {
    newContent: string
    mutationId: string
}

export function writeBundleFile(slug: string, path: string, body: BundleFileWrite): void {
    bundleOverlay.set(`${slug}:${path}`, body.newContent)
    recordMutation(`bundle-file:${slug}:${path}`, body.mutationId)
}

export interface RevisionSpecPatchWrite {
    patch: Partial<RevisionSpec>
    mutationId: string
}

export function writeRevisionSpecPatch(slug: string, revisionId: string, body: RevisionSpecPatchWrite): void {
    const prev = revisionSpecOverlay.get(revisionId) ?? {}
    revisionSpecOverlay.set(revisionId, { ...prev, ...body.patch })
    recordMutation(`revision-spec:${slug}:${revisionId}`, body.mutationId)
}

function baseBundleForApplication(applicationId: string): BundleFile[] {
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

/* ── Mutation event emitter ──────────────────────────────────────── */

export interface MutationEvent {
    entityKey: string
    mutationId: string
    /** Monotonic per-entity counter — bumped on every recordMutation. */
    revision: number
    /** Wall-clock ms (Date.now()). */
    at: number
}

type Listener = (e: MutationEvent) => void

const eventListeners = new Set<Listener>()
const revisionCounters = new Map<string, number>()

export function subscribeMutationEvents(listener: Listener): () => void {
    eventListeners.add(listener)
    return () => {
        eventListeners.delete(listener)
    }
}

function recordMutation(entityKey: string, mutationId: string): void {
    bumpAndEmit(entityKey, mutationId)
    const parent = parentEntityKey(entityKey)
    if (parent) {
        bumpAndEmit(parent, mutationId)
    }
}

function bumpAndEmit(entityKey: string, mutationId: string): void {
    const next = (revisionCounters.get(entityKey) ?? 0) + 1
    revisionCounters.set(entityKey, next)
    const event: MutationEvent = { entityKey, mutationId, revision: next, at: Date.now() }
    for (const listener of eventListeners) {
        try {
            listener(event)
        } catch {
            // Listener bug — swallow so other listeners still receive the event.
        }
    }
}

function parentEntityKey(entityKey: string): string | null {
    if (entityKey.startsWith('bundle-file:')) {
        const [, slug] = entityKey.split(':')
        return `bundle:${slug}`
    }
    if (entityKey.startsWith('revision-spec:')) {
        const [, slug] = entityKey.split(':')
        return `revisions:${slug}`
    }
    return null
}
