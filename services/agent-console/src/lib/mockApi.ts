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
    weeklyDigestRevisions,
} from '@posthog/agent-chat/fixtures'
import type {
    AgentApplicationFixture,
    AgentRevisionFixture,
    AgentStats,
    FleetStats,
    LogEntry,
} from '@posthog/agent-chat/fixtures'

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
