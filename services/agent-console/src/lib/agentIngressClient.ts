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
 *
 * Preview path: when a `preview` option is supplied, the client
 * keeps the same URL prefix but flips the slug to `<slug>-<revHex>`
 * (the ingress's revision-routing form) and attaches the short-lived
 * JWT Django minted via `getPreviewToken(...)`. POST/DELETE carry it
 * as the `x-agent-preview-token` header; `EventSource` for `/listen`
 * carries it as `?preview_token=` in the URL because the API can't
 * set custom headers. Ingress accepts either source. The runner
 * itself doesn't know "live" vs "preview" — same trigger handlers,
 * same path. See `docs/agent-platform/plans/draft-preview-auth.md`.
 */

const LIVE_PREFIX = '/api/agents/v1/agents'

export interface PreviewOpts {
    /**
     * Slug to use in the ingress URL — the `<application_slug>-<revHex>`
     * shape that ingress's resolver uses to pick a specific non-live
     * revision. Returned by `getPreviewToken` as `ingress_slug`.
     */
    ingressSlug: string
    /** Short-lived HS256 JWT from `getPreviewToken`. */
    token: string
}

/**
 * Build the ingress URL. For live (`preview == null`) it's just the
 * public chat path. For preview it swaps the slug for the rev-hex form
 * and (for the SSE listen case) appends `preview_token=` in the query
 * — EventSource can't set headers, so the URL is the only channel.
 */
function buildUrl(
    slug: string,
    rest: 'run' | 'send' | 'cancel' | 'listen',
    preview: PreviewOpts | undefined,
    query: string | undefined,
    embedTokenInQuery: boolean
): string {
    const effectiveSlug = preview?.ingressSlug ?? slug
    const tokenQuery = preview && embedTokenInQuery ? `preview_token=${encodeURIComponent(preview.token)}` : undefined
    const combined = [query, tokenQuery].filter(Boolean).join('&')
    const qs = combined ? `?${combined}` : ''
    return `${LIVE_PREFIX}/${encodeURIComponent(effectiveSlug)}/${rest}${qs}`
}

function previewHeaders(preview?: PreviewOpts): Record<string, string> {
    return preview ? { 'x-agent-preview-token': preview.token } : {}
}

export class IngressError extends Error {
    readonly status: number
    constructor(status: number, message: string) {
        super(message)
        this.status = status
        this.name = 'IngressError'
    }
}

async function postJson<TBody, TResult>(
    url: string,
    body: TBody,
    extraHeaders: Record<string, string> = {}
): Promise<TResult> {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...extraHeaders },
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

export async function startRun(
    slug: string,
    message: string,
    opts: { externalKey?: string; preview?: PreviewOpts } = {}
): Promise<RunResponse> {
    return postJson<{ message: string; external_key?: string }, RunResponse>(
        buildUrl(slug, 'run', opts.preview, undefined, false),
        opts.externalKey ? { message, external_key: opts.externalKey } : { message },
        previewHeaders(opts.preview)
    )
}

export async function sendMessage(
    slug: string,
    sessionId: string,
    message: string,
    opts: { preview?: PreviewOpts } = {}
): Promise<{ ok: true }> {
    return postJson<{ session_id: string; message: string }, { ok: true }>(
        buildUrl(slug, 'send', opts.preview, undefined, false),
        { session_id: sessionId, message },
        previewHeaders(opts.preview)
    )
}

export async function cancelSession(
    slug: string,
    sessionId: string,
    opts: { preview?: PreviewOpts } = {}
): Promise<{ ok: true; idempotent?: boolean; state?: string }> {
    return postJson<{ session_id: string }, { ok: true; idempotent?: boolean; state?: string }>(
        buildUrl(slug, 'cancel', opts.preview, undefined, false),
        { session_id: sessionId },
        previewHeaders(opts.preview)
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
    handlers: { onEvent: (event: SessionEvent) => void; onError?: (err: unknown) => void },
    opts: { preview?: PreviewOpts } = {}
): () => void {
    // `true` → embed `preview_token=` in the query string; EventSource
    // can't set the `x-agent-preview-token` header so the URL is the
    // only channel for the JWT. Ingress accepts either source.
    const url = buildUrl(slug, 'listen', opts.preview, `session_id=${encodeURIComponent(sessionId)}`, true)
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
