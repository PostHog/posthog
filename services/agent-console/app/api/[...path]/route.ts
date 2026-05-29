/**
 * Catch-all API proxy → PostHog Django (+ later agent-ingress).
 *
 * Browser hits same-origin `/api/projects/...` — this handler reads the
 * sealed session cookie, attaches `Authorization: Bearer <access_token>`,
 * and forwards the request to the right upstream. The token never
 * reaches the browser; cookies stay HTTP-only.
 *
 * Routing:
 *   `/api/agents/v1/...` → `posthogAgentsBaseUrl()` (agent-ingress)
 *   `/api/...`           → `posthogBaseUrl()` (PostHog Django)
 *
 * On 401: try to refresh the access_token using the refresh_token,
 * then replay the request once. If refresh also fails we clear the
 * session and surface 401 to the browser (the middleware redirects
 * the next navigation back to /login).
 *
 * Streaming-aware: passes through response bodies as-is so SSE
 * (`text/event-stream`) Just Works without buffering.
 *
 * The `/api/auth/*` routes are NOT handled here — Next.js routes those
 * to their own handlers first because they're more specific paths.
 */

import { NextRequest, NextResponse } from 'next/server'

import { posthogAgentsBaseUrl, posthogBaseUrl } from '@/lib/auth/config'
import { clearSession, getSession, setSession, type SessionPayload } from '@/lib/auth/session'
import { OAuthTokenError, refreshAccessToken } from '@/lib/auth/tokens'

export const dynamic = 'force-dynamic'

const HANDLED_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const

async function handle(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }): Promise<Response> {
    const { path } = await params
    const segments = path ?? []

    // Defensive: `/api/auth/*` is supposed to be handled by its own
    // routes — but if Next.js's routing ever overlaps, bail loudly
    // rather than proxying upstream and confusing things.
    if (segments[0] === 'auth') {
        return NextResponse.json({ error: 'unhandled_auth_route' }, { status: 404 })
    }

    const session = await getSession()
    if (!session) {
        return NextResponse.json({ error: 'unauthenticated' }, { status: 401 })
    }

    const upstream = buildUpstreamUrl(segments, request.nextUrl.search)
    const init = await buildRequestInit(request)

    const first = await proxy(upstream, init, session)
    if (first.status !== 401) {
        return first
    }

    // 401 — try one refresh + replay.
    let refreshed: SessionPayload
    try {
        refreshed = await refreshAccessToken(session.refreshToken)
    } catch (err) {
        if (err instanceof OAuthTokenError && (err.status === 400 || err.status === 401)) {
            await clearSession()
        }
        return NextResponse.json({ error: 'unauthenticated' }, { status: 401 })
    }
    await setSession(refreshed)

    // Body is a stream that may have been consumed; rebuild from the
    // original request (cheap because Next has the body buffered for
    // the route handler).
    const replayInit = await buildRequestInit(request)
    return await proxy(upstream, replayInit, refreshed)
}

function buildUpstreamUrl(segments: string[], search: string): string {
    if (segments[0] === 'agents' && segments[1] === 'v1') {
        const rest = segments.slice(2).join('/')
        return `${posthogAgentsBaseUrl()}/${rest}${search}`
    }
    const rest = segments.join('/')
    return `${posthogBaseUrl()}/api/${rest}${search}`
}

async function buildRequestInit(request: NextRequest): Promise<RequestInit> {
    const headers = new Headers()
    request.headers.forEach((value, key) => {
        const lower = key.toLowerCase()
        // Strip hop-by-hop + cookie headers — the upstream auth is the
        // bearer token, not whatever cookies the browser may also send.
        if (
            lower === 'host' ||
            lower === 'cookie' ||
            lower === 'connection' ||
            lower === 'content-length' ||
            lower === 'authorization'
        ) {
            return
        }
        headers.set(key, value)
    })

    const init: RequestInit = {
        method: request.method,
        headers,
        // @ts-expect-error — `duplex` is required by Node fetch for streamed bodies
        duplex: 'half',
    }

    if (request.method !== 'GET' && request.method !== 'HEAD') {
        const body = await request.arrayBuffer()
        if (body.byteLength > 0) {
            init.body = body
        }
    }

    return init
}

async function proxy(url: string, init: RequestInit, session: SessionPayload): Promise<Response> {
    const headers = new Headers(init.headers)
    headers.set('Authorization', `Bearer ${session.accessToken}`)
    return await fetch(url, { ...init, headers })
}

export const GET = handle
export const POST = handle
export const PUT = handle
export const PATCH = handle
export const DELETE = handle

void HANDLED_METHODS
