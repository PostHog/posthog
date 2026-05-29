/**
 * Typed REST client for the agent console.
 *
 * Every read/write the console does goes through here. The shape
 * mirrors the real PostHog REST + agent-ingress surfaces; v0 runs
 * against MSW (Storybook only) and v0.1+ swaps in a Next.js rewrite
 * to the real backends without app-side changes.
 *
 * **Path conventions — same-origin to avoid CORS.** Two prefixes
 * Next.js proxies to different backends in prod (configured in
 * `next.config.ts → rewrites()`):
 *
 *   `posthogUrl()`        → `/api/projects/<projectId>/agent_*`
 *                            → PostHog Django REST
 *                            (persistent state: apps, revisions,
 *                             bundles, sessions, logs, stats)
 *   `posthogAgentsUrl()`  → `/api/agents/v1/*`
 *                            → agent-ingress (runtime + streaming:
 *                              session messages, /listen,
 *                              mutation event stream)
 *
 * App code has no awareness of MSW — these functions issue real
 * `fetch` calls. In Storybook they're intercepted; in production
 * they're proxied by Next.js. Same-origin everywhere.
 *
 * Conventions:
 *   - Lists return the inner array (the wire shape is `{ results: T[] }`).
 *   - Detail returns the inner record.
 *   - Writes return `{ mutationId }` and may emit a server-side
 *     mutation event picked up by the SSE stream (`subscribeMutations`).
 */

import type { ChatSession } from '@posthog/agent-chat'
import type {
    AgentApplicationFixture,
    AgentRevisionFixture,
    AgentStats,
    BundleFile,
    FleetStats,
    LogEntry,
} from '@posthog/agent-chat/fixtures'

// v0: hardcoded project. v0.1: read from the session / org context.
const PROJECT_ID = 2

function posthogUrl(suffix: string): string {
    return `/api/projects/${PROJECT_ID}${suffix}`
}

function posthogAgentsUrl(suffix: string): string {
    return `/api/agents/v1${suffix}`
}

async function getJson<T>(url: string): Promise<T> {
    const res = await fetch(url, { headers: { Accept: 'application/json' } })
    if (!res.ok) {
        throw new ApiError(res.status, await safeError(res))
    }
    return (await res.json()) as T
}

async function patchJson<TBody, TResult>(url: string, body: TBody): Promise<TResult> {
    const res = await fetch(url, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
    })
    if (!res.ok) {
        throw new ApiError(res.status, await safeError(res))
    }
    return (await res.json()) as TResult
}

async function putJson<TBody, TResult>(url: string, body: TBody): Promise<TResult> {
    const res = await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
    })
    if (!res.ok) {
        throw new ApiError(res.status, await safeError(res))
    }
    return (await res.json()) as TResult
}

async function safeError(res: Response): Promise<string> {
    try {
        const body = (await res.json()) as { error?: string }
        return body.error ?? `${res.status} ${res.statusText}`
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

/* ── Read endpoints ──────────────────────────────────────────────── */

export async function listAgents(opts: { includeArchived?: boolean } = {}): Promise<AgentApplicationFixture[]> {
    const qs = opts.includeArchived ? '?include_archived=true' : ''
    const { results } = await getJson<{ results: AgentApplicationFixture[] }>(posthogUrl(`/agent_applications/${qs}`))
    return results
}

export async function getAgent(slug: string): Promise<AgentApplicationFixture> {
    return getJson<AgentApplicationFixture>(posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/`))
}

export async function listRevisions(slug: string): Promise<AgentRevisionFixture[]> {
    const { results } = await getJson<{ results: AgentRevisionFixture[] }>(
        posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/revisions/`)
    )
    return results
}

export async function getBundle(slug: string): Promise<BundleFile[]> {
    const { results } = await getJson<{ results: BundleFile[] }>(
        posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/bundle/`)
    )
    return results
}

export async function getAgentStats(slug: string): Promise<AgentStats> {
    return getJson<AgentStats>(posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/stats/`))
}

export async function listSessionsForAgent(slug: string): Promise<ChatSession[]> {
    const { results } = await getJson<{ results: ChatSession[] }>(
        posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/sessions/`)
    )
    return results
}

export async function getLiveSessionCountForAgent(slug: string): Promise<number> {
    const { count } = await getJson<{ count: number }>(
        posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/live_session_count/`)
    )
    return count
}

export async function getSession(sessionId: string): Promise<ChatSession> {
    return getJson<ChatSession>(posthogUrl(`/agent_sessions/${encodeURIComponent(sessionId)}/`))
}

export async function listLogsForSession(sessionId: string): Promise<LogEntry[]> {
    const { results } = await getJson<{ results: LogEntry[] }>(
        posthogUrl(`/agent_sessions/${encodeURIComponent(sessionId)}/logs/`)
    )
    return results
}

export async function getFleetStats(): Promise<FleetStats> {
    return getJson<FleetStats>(posthogUrl(`/agent_fleet/stats/`))
}

export async function listLiveSessions(): Promise<ChatSession[]> {
    const { results } = await getJson<{ results: ChatSession[] }>(posthogUrl(`/agent_fleet/live_sessions/`))
    return results
}

/* ── Write endpoints ─────────────────────────────────────────────── */

export interface BundleFileWriteRequest {
    newContent: string
    mutationId: string
}

export async function writeBundleFile(
    slug: string,
    path: string,
    body: BundleFileWriteRequest
): Promise<{ mutationId: string }> {
    return putJson<BundleFileWriteRequest, { ok: true; mutationId: string }>(
        posthogUrl(`/agent_applications/${encodeURIComponent(slug)}/bundle/files/?path=${encodeURIComponent(path)}`),
        body
    )
}

type RevisionSpec = AgentRevisionFixture['spec']

export interface RevisionSpecPatchRequest {
    /** Slug of the application this revision belongs to. The handler emits an
     * entityKey scoped by it so consumers can subscribe without needing the
     * internal application id. */
    applicationSlug: string
    patch: Partial<RevisionSpec>
    mutationId: string
}

export async function patchRevisionSpec(
    revisionId: string,
    body: RevisionSpecPatchRequest
): Promise<{ mutationId: string }> {
    return patchJson<RevisionSpecPatchRequest, { ok: true; mutationId: string }>(
        posthogUrl(`/agent_revisions/${encodeURIComponent(revisionId)}/spec/`),
        body
    )
}

/* ── Mutation event stream ───────────────────────────────────────── */

export interface MutationEvent {
    entityKey: string
    mutationId: string
    revision: number
    at: number
}

/**
 * Subscribe to the server-side mutation event stream. Returns an
 * unsubscribe fn. Internally opens an EventSource that the real
 * backend serves as text/event-stream; in Storybook MSW intercepts.
 */
export function subscribeMutations(listener: (event: MutationEvent) => void): () => void {
    const source = new EventSource(posthogAgentsUrl(`/events/stream`))
    const handler = (e: MessageEvent): void => {
        try {
            listener(JSON.parse(e.data) as MutationEvent)
        } catch {
            // Bad payload — skip; the stream itself is fine.
        }
    }
    source.addEventListener('mutation', handler)
    return () => {
        source.removeEventListener('mutation', handler)
        source.close()
    }
}
