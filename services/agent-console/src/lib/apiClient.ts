/**
 * Typed REST client for the agent console.
 *
 * Paths mirror the real PostHog Django REST surface (see
 * `products/agent_stack/backend/api.py`). The browser hits
 * same-origin `/api/projects/<teamId>/...` which the Next.js
 * catch-all route forwards to Django with the user's OAuth token
 * attached server-side.
 *
 * Every call takes the team id explicitly — callers pull it from
 * `useSessionTeamId()` (sourced from `/api/auth/me`). No module-level
 * project state, so switching teams later doesn't require an app
 * reload.
 *
 * The console is read-mostly. Writes are the agent runner's job: the
 * user asks the concierge dock, the agent POSTs to the same Django
 * endpoints via MCP, the console refetches on its next navigation.
 */

import type { ChatSession } from '@posthog/agent-chat'
import type {
    AgentApplicationFixture,
    AgentRevisionFixture,
    AgentStats,
    BundleFile,
    BundleFileLanguage,
    FleetStats,
    LogEntry,
} from '@posthog/agent-chat/fixtures'

function posthogUrl(teamId: number, suffix: string): string {
    return `/api/projects/${teamId}${suffix}`
}

async function getJson<T>(url: string): Promise<T> {
    const res = await fetch(url, { headers: { Accept: 'application/json' } })
    if (!res.ok) {
        throw new ApiError(res.status, await safeError(res))
    }
    return (await res.json()) as T
}

async function safeError(res: Response): Promise<string> {
    try {
        const body = (await res.json()) as { error?: string; detail?: string }
        return body.error ?? body.detail ?? `${res.status} ${res.statusText}`
    } catch {
        return `${res.status} ${res.statusText}`
    }
}

export class ApiError extends Error {
    readonly status: number
    constructor(status: number, message: string) {
        super(message)
        this.status = status
        this.name = 'ApiError'
    }
}

/* ── Applications ────────────────────────────────────────────────── */

export async function listAgents(
    teamId: number,
    opts: { includeArchived?: boolean } = {}
): Promise<AgentApplicationFixture[]> {
    const qs = opts.includeArchived ? '?include_archived=true' : ''
    const { results } = await getJson<{ results: AgentApplicationFixture[] }>(
        posthogUrl(teamId, `/agent_applications/${qs}`)
    )
    return results
}

export async function getAgent(teamId: number, slug: string): Promise<AgentApplicationFixture> {
    return getJson<AgentApplicationFixture>(posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/`))
}

/* ── Revisions ───────────────────────────────────────────────────── */

export async function listRevisions(teamId: number, slug: string): Promise<AgentRevisionFixture[]> {
    const { results } = await getJson<{ results: AgentRevisionFixture[] }>(
        posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/revisions/`)
    )
    return results
}

/**
 * Bulk-pull a revision's bundle. Django shape: `{ files: { path:
 * content }, ... }`. Transformed here so consumers get the typed
 * `BundleFile[]` array.
 */
export async function getBundle(teamId: number, slug: string, revisionId: string): Promise<BundleFile[]> {
    const raw = await getJson<{ files: Record<string, string> }>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/revisions/${encodeURIComponent(revisionId)}/bundle/`
        )
    )
    return Object.entries(raw.files).map(([path, content]) => ({
        path,
        content,
        language: languageForPath(path),
    }))
}

function languageForPath(path: string): BundleFileLanguage {
    if (path.endsWith('.md') || path.endsWith('.mdx')) {
        return 'markdown'
    }
    if (path.endsWith('.ts') || path.endsWith('.tsx')) {
        return 'typescript'
    }
    if (path.endsWith('.json')) {
        return 'json'
    }
    return 'text'
}

/* ── Sessions ────────────────────────────────────────────────────── */

export async function listSessionsForAgent(teamId: number, slug: string): Promise<ChatSession[]> {
    const { results } = await getJson<{ results: ChatSession[] }>(
        posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/sessions/`)
    )
    return results
}

export async function getSession(teamId: number, slug: string, sessionId: string): Promise<ChatSession> {
    return getJson<ChatSession>(
        posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/sessions/${encodeURIComponent(sessionId)}/`)
    )
}

export async function listLogsForSession(teamId: number, slug: string, sessionId: string): Promise<LogEntry[]> {
    const { results } = await getJson<{ results: LogEntry[] }>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/sessions/${encodeURIComponent(sessionId)}/logs/`
        )
    )
    return results
}

/* ── Read endpoints not yet served by Django — Phase C ───────────── */

export async function getAgentStats(teamId: number, slug: string): Promise<AgentStats> {
    return getJson<AgentStats>(posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/stats/`))
}

export async function getFleetStats(teamId: number): Promise<FleetStats> {
    return getJson<FleetStats>(posthogUrl(teamId, `/agent_fleet/stats/`))
}

export async function listLiveSessions(teamId: number): Promise<ChatSession[]> {
    const { results } = await getJson<{ results: ChatSession[] }>(posthogUrl(teamId, `/agent_fleet/live_sessions/`))
    return results
}
