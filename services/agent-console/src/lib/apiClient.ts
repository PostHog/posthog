/**
 * Typed REST client for the agent console.
 *
 * Every read the console does goes through here. Paths mirror the
 * real PostHog Django REST surface (see
 * `products/agent_stack/backend/api.py`). Storybook intercepts via
 * MSW; production Next.js proxies via `next.config.mjs → rewrites()`.
 *
 * Same-origin to avoid CORS. Next.js rewrites `/api/projects/...` to
 * the PostHog Django REST surface. When chat send/listen lands later
 * it'll add a `posthogAgentsUrl()` helper for `/api/agents/v1/*` →
 * agent-ingress.
 *
 * The console is read-mostly. Writes are the agent runner's job; when
 * the user wants to change something they ask the concierge dock, the
 * agent POSTs to the same Django endpoints via MCP, the console
 * refetches on its next navigation. The agent navigates the console
 * via the `@posthog/ui/focus` tool — see `Dock.tsx` for the URL map.
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

// v0: hardcoded project. v0.1: read from the session / org context.
const PROJECT_ID = 2

function posthogUrl(suffix: string): string {
    return `/api/projects/${PROJECT_ID}${suffix}`
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

export async function listAgents(opts: { includeArchived?: boolean } = {}): Promise<AgentApplicationFixture[]> {
    const qs = opts.includeArchived ? '?include_archived=true' : ''
    const { results } = await getJson<{ results: AgentApplicationFixture[] }>(posthogUrl(`/agent_applications/${qs}`))
    return results
}

export async function getAgent(slug: string): Promise<AgentApplicationFixture> {
    return getJson<AgentApplicationFixture>(posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/`))
}

/* ── Revisions ───────────────────────────────────────────────────── */

export async function listRevisions(slug: string): Promise<AgentRevisionFixture[]> {
    const { results } = await getJson<{ results: AgentRevisionFixture[] }>(
        posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/revisions/`)
    )
    return results
}

/**
 * Bulk-pull a revision's bundle. Django shape: `{ files: { path:
 * content }, ... }`. Transformed here so consumers get the typed
 * `BundleFile[]` array.
 */
export async function getBundle(slug: string, revisionId: string): Promise<BundleFile[]> {
    const raw = await getJson<{ files: Record<string, string> }>(
        posthogUrl(
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

export async function listSessionsForAgent(slug: string): Promise<ChatSession[]> {
    const { results } = await getJson<{ results: ChatSession[] }>(
        posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/sessions/`)
    )
    return results
}

export async function getSession(slug: string, sessionId: string): Promise<ChatSession> {
    return getJson<ChatSession>(
        posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/sessions/${encodeURIComponent(sessionId)}/`)
    )
}

export async function listLogsForSession(slug: string, sessionId: string): Promise<LogEntry[]> {
    const { results } = await getJson<{ results: LogEntry[] }>(
        posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/sessions/${encodeURIComponent(sessionId)}/logs/`)
    )
    return results
}

/* ── Read endpoints not yet served by Django — Phase C ───────────── */

export async function getAgentStats(slug: string): Promise<AgentStats> {
    return getJson<AgentStats>(posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/stats/`))
}

export async function getFleetStats(): Promise<FleetStats> {
    return getJson<FleetStats>(posthogUrl(`/agent_fleet/stats/`))
}

export async function listLiveSessions(): Promise<ChatSession[]> {
    const { results } = await getJson<{ results: ChatSession[] }>(posthogUrl(`/agent_fleet/live_sessions/`))
    return results
}
