/**
 * Typed client for agent-ingress's chat trigger.
 *
 * Browser hits same-origin `/api/agents/v1/agents/<slug>/...` which
 * the Next.js catch-all proxy forwards to `posthogAgentsBaseUrl()`
 * with the user's OAuth bearer token attached server-side. The
 * agent's `spec.auth.mode` controls whether the token is actually
 * required upstream (public-mode agents ignore it).
 *
 * Contract (see `services/agent-ingress/src/triggers/chat.ts`):
 *   POST   /agents/<slug>/run     → { ok, session_id, resumed, principal }
 *   POST   /agents/<slug>/send    → { ok }
 *   POST   /agents/<slug>/cancel  → { ok, idempotent?, state? }
 *   GET    /agents/<slug>/listen  → text/event-stream
 */

const PREFIX = '/api/agents/v1/agents'

export class IngressError extends Error {
    readonly status: number
    constructor(status: number, message: string) {
        super(message)
        this.status = status
        this.name = 'IngressError'
    }
}

async function postJson<TBody, TResult>(url: string, body: TBody): Promise<TResult> {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
    })
    if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new IngressError(res.status, `${res.status} ${res.statusText}: ${text}`)
    }
    return (await res.json()) as TResult
}

export interface RunResponse {
    ok: true
    session_id: string
    resumed: boolean
    principal: unknown
}

export async function startRun(slug: string, message: string, externalKey?: string): Promise<RunResponse> {
    return postJson<{ message: string; external_key?: string }, RunResponse>(
        `${PREFIX}/${encodeURIComponent(slug)}/run`,
        externalKey ? { message, external_key: externalKey } : { message }
    )
}

export async function sendMessage(slug: string, sessionId: string, message: string): Promise<{ ok: true }> {
    return postJson<{ session_id: string; message: string }, { ok: true }>(
        `${PREFIX}/${encodeURIComponent(slug)}/send`,
        { session_id: sessionId, message }
    )
}

export async function cancelSession(
    slug: string,
    sessionId: string
): Promise<{ ok: true; idempotent?: boolean; state?: string }> {
    return postJson<{ session_id: string }, { ok: true; idempotent?: boolean; state?: string }>(
        `${PREFIX}/${encodeURIComponent(slug)}/cancel`,
        { session_id: sessionId }
    )
}

/**
 * Subscribe to the SSE stream for one session. Returns a close fn.
 * The listener receives every event the runner publishes for the
 * session — see `SessionEvent` for the kind catalogue.
 */
export interface SessionEvent {
    session_id: string
    kind: string
    data: Record<string, unknown>
    ts: string
}

export function listen(
    slug: string,
    sessionId: string,
    handlers: { onEvent: (event: SessionEvent) => void; onError?: (err: unknown) => void }
): () => void {
    const url = `${PREFIX}/${encodeURIComponent(slug)}/listen?session_id=${encodeURIComponent(sessionId)}`
    const source = new EventSource(url)
    const onMessage = (e: MessageEvent): void => {
        try {
            handlers.onEvent(JSON.parse(e.data) as SessionEvent)
        } catch (err) {
            handlers.onError?.(err)
        }
    }
    const onErrorRaw = (e: Event): void => {
        handlers.onError?.(e)
    }
    source.addEventListener('message', onMessage)
    source.addEventListener('error', onErrorRaw)
    return () => {
        source.removeEventListener('message', onMessage)
        source.removeEventListener('error', onErrorRaw)
        source.close()
    }
}
