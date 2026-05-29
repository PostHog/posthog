/**
 * Mocked PostHog REST client.
 *
 * v0 only — every method returns a fixture. v0.1 swaps this module for the
 * generated TypeScript client (`hogli build:openapi` output). Method
 * signatures are chosen to match the future generated shape so call sites
 * don't move when we swap implementations.
 *
 * Includes an artificial latency knob so loading states get exercised in
 * Storybook (stories can pass `latencyMs: 0` for snapshot determinism).
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

export interface MockApiOptions {
    /** Artificial delay before each call resolves. Defaults to 0 (fast for snapshots). */
    latencyMs?: number
    /** Include archived agents in `listAgents`. */
    includeArchived?: boolean
}

function delay(ms: number): Promise<void> {
    return ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve()
}

export async function listAgents(opts: MockApiOptions = {}): Promise<AgentApplicationFixture[]> {
    await delay(opts.latencyMs ?? 0)
    return opts.includeArchived ? agentsWithArchived : agents
}

export async function getAgentBySlug(slug: string, opts: MockApiOptions = {}): Promise<AgentApplicationFixture | null> {
    await delay(opts.latencyMs ?? 0)
    return (opts.includeArchived ? agentsWithArchived : agents).find((a) => a.slug === slug) ?? null
}

export async function listRevisions(applicationId: string, opts: MockApiOptions = {}): Promise<AgentRevisionFixture[]> {
    await delay(opts.latencyMs ?? 0)
    return listRevisionsSync(applicationId)
}

/** Sync variant — same overlay + base merge, used by client hooks on refetch. */
export function listRevisionsSync(applicationId: string): AgentRevisionFixture[] {
    const base = baseRevisionsForApplication(applicationId)
    return base.map((rev) => {
        const patch = revisionSpecOverlay.get(rev.id)
        if (!patch) {
            return rev
        }
        return { ...rev, spec: { ...rev.spec, ...patch } as RevisionSpec }
    })
}

function baseRevisionsForApplication(applicationId: string): AgentRevisionFixture[] {
    if (applicationId === weeklyDigest.id) {
        return weeklyDigestRevisions
    }
    return []
}

/* ──────────────────────────────────────────────────────────────────────
 * Fleet-level reads — power the agents-list stat strip + live-now panel.
 *
 * v0.1 maps to:
 *  - listLiveSessions     →  GET /api/projects/:t/agent_sessions/?state=live
 *  - getFleetStats        →  GET /api/projects/:t/agent_stats/  (new endpoint;
 *                            backed by per-turn-cost-capture + session counts)
 *  - countLiveSessionsForAgent  →  derived client-side from listLiveSessions
 * ──────────────────────────────────────────────────────────────────── */

export async function listLiveSessions(opts: MockApiOptions = {}): Promise<ChatSession[]> {
    await delay(opts.latencyMs ?? 0)
    return fleetLiveSessions
}

export async function getFleetStats(opts: MockApiOptions = {}): Promise<FleetStats> {
    await delay(opts.latencyMs ?? 0)
    return fleetStats
}

export async function countLiveSessionsForAgent(applicationId: string, opts: MockApiOptions = {}): Promise<number> {
    await delay(opts.latencyMs ?? 0)
    return liveSessionCountsByAgent[applicationId] ?? 0
}

/* Per-agent reads — back the agent-detail tabs. */

export async function listSessionsForAgent(applicationId: string, opts: MockApiOptions = {}): Promise<ChatSession[]> {
    await delay(opts.latencyMs ?? 0)
    return listSessionsForAgentFixture(applicationId)
}

export async function getAgentStats(applicationId: string, opts: MockApiOptions = {}): Promise<AgentStats> {
    await delay(opts.latencyMs ?? 0)
    return getAgentStatsFixture(applicationId)
}

/* Session detail — back the /agents/<slug>/sessions/<id> page.
 *
 * v0.1 maps to:
 *   - getSession      → GET /api/projects/:t/agent_sessions/<id>/
 *   - listLogsForSession → PostHog logs query: session_id = <id>
 */

export async function getSession(sessionId: string, opts: MockApiOptions = {}): Promise<ChatSession | null> {
    await delay(opts.latencyMs ?? 0)
    // Search through every agent's session history for the matching id.
    for (const agent of agents) {
        const found = listSessionsForAgentFixture(agent.id).find((s) => s.id === sessionId)
        if (found) {
            return found
        }
    }
    // Also check live-now in case the session is fleet-level only.
    return fleetLiveSessions.find((s) => s.id === sessionId) ?? null
}

export async function listLogsForSession(sessionId: string, opts: MockApiOptions = {}): Promise<LogEntry[]> {
    await delay(opts.latencyMs ?? 0)
    return listLogsForSessionFixture(sessionId)
}

/* ──────────────────────────────────────────────────────────────────────
 * Bundle reads + the mutation registry.
 *
 * In the real platform, "the agent just changed agent.md" arrives via two
 * channels: (1) the runner protocol's `mutations[]` field on a tool
 * result, (2) the next bundle fetch returning new content. The console
 * needs both — `mutationId` so the *focused* view can re-fetch + flair,
 * and a per-entity revision counter so *any* mounted view of that entity
 * can flair the moment its data moves underneath it (when focus mode is
 * on; off-mode views just refetch silently).
 *
 * For v0 we mock the whole thing in-process: a module-level overlay map
 * absorbs writes, every read merges overlay onto the base fixture, and
 * the registry notifies subscribers so UI can refetch + flair.
 *
 * Conventions:
 *   entityKey shape       form
 *   ─────────────────     ────────────────────────────────────────
 *   bundle-file           `bundle-file:<applicationId>:<path>`
 *   bundle                `bundle:<applicationId>`
 *   revision-spec         `revision-spec:<applicationId>:<revisionId>`
 *   revisions             `revisions:<applicationId>`
 *   agent                 `agent:<applicationId>`
 *
 * v0.1+ replaces this whole section with a real client backed by the
 * janitor's bundle service + a server-sent `mutations` stream.
 * ──────────────────────────────────────────────────────────────── */

export type EntityKey = string

interface MutationRecord {
    /** Monotonic per-entity counter; bumps every time `recordMutation` runs. */
    revision: number
    /** The most recent mutation_id. Useful for focus-event correlation. */
    mutationId: string
    /** Wall-clock of the bump. Used by flair animation to time itself. */
    at: number
}

type MutationListener = (record: MutationRecord) => void

const mutationRegistry = new Map<EntityKey, MutationRecord>()
const listeners = new Map<EntityKey, Set<MutationListener>>()

export function getMutationRecord(entityKey: EntityKey): MutationRecord | null {
    return mutationRegistry.get(entityKey) ?? null
}

/** Subscribe to changes for a specific entity. Returns an unsubscribe fn. */
export function subscribeMutation(entityKey: EntityKey, listener: MutationListener): () => void {
    let set = listeners.get(entityKey)
    if (!set) {
        set = new Set()
        listeners.set(entityKey, set)
    }
    set.add(listener)
    return () => {
        set?.delete(listener)
    }
}

export function recordMutation(entityKey: EntityKey, mutationId: string): MutationRecord {
    const prev = mutationRegistry.get(entityKey)
    const record: MutationRecord = {
        revision: (prev?.revision ?? 0) + 1,
        mutationId,
        at: Date.now(),
    }
    mutationRegistry.set(entityKey, record)
    listeners.get(entityKey)?.forEach((fn) => fn(record))
    // Cascade to the per-app parent key so consumers watching the
    // aggregate (bundle tree, revisions list) refetch without
    // subscribing per-leaf.
    const parentKey = parentEntityKey(entityKey)
    if (parentKey) {
        const parentPrev = mutationRegistry.get(parentKey)
        const parentRecord: MutationRecord = {
            revision: (parentPrev?.revision ?? 0) + 1,
            mutationId,
            at: record.at,
        }
        mutationRegistry.set(parentKey, parentRecord)
        listeners.get(parentKey)?.forEach((fn) => fn(parentRecord))
    }
    return record
}

function parentEntityKey(entityKey: EntityKey): EntityKey | null {
    if (entityKey.startsWith('bundle-file:')) {
        const [, applicationId] = entityKey.split(':')
        return `bundle:${applicationId}`
    }
    if (entityKey.startsWith('revision-spec:')) {
        const [, applicationId] = entityKey.split(':')
        return `revisions:${applicationId}`
    }
    return null
}

/* ── Bundle overlay + reads ──────────────────────────────────────── */

/** `${applicationId}:${path}` → patched content. v0 demo overlay. */
const bundleOverlay = new Map<string, string>()

export function applyBundleFilePatch(applicationId: string, path: string, newContent: string): void {
    bundleOverlay.set(`${applicationId}:${path}`, newContent)
}

function baseBundleForApplication(applicationId: string): BundleFile[] {
    if (applicationId === weeklyDigest.id) {
        return weeklyDigestBundle
    }
    return []
}

export async function getBundleForApplication(applicationId: string, opts: MockApiOptions = {}): Promise<BundleFile[]> {
    await delay(opts.latencyMs ?? 0)
    const base = baseBundleForApplication(applicationId)
    return base.map((f) => {
        const patched = bundleOverlay.get(`${applicationId}:${f.path}`)
        return patched !== undefined ? { ...f, content: patched } : f
    })
}

/** Sync variant — used by client-side hooks that refetch on mutation. */
export function getBundleForApplicationSync(applicationId: string): BundleFile[] {
    const base = baseBundleForApplication(applicationId)
    return base.map((f) => {
        const patched = bundleOverlay.get(`${applicationId}:${f.path}`)
        return patched !== undefined ? { ...f, content: patched } : f
    })
}

/* ── Revision spec overlay ───────────────────────────────────────── */

/**
 * `revisionId` → shallow patch merged on top of the base spec. v0 demo
 * overlay; v0.1 a real spec mutation creates a new revision instead of
 * patching in place.
 */
const revisionSpecOverlay = new Map<string, Partial<RevisionSpec>>()

export function applyRevisionSpecPatch(revisionId: string, patch: Partial<RevisionSpec>): void {
    const prev = revisionSpecOverlay.get(revisionId) ?? {}
    revisionSpecOverlay.set(revisionId, { ...prev, ...patch })
}
