// Hono application factory for the agent-proxy service.
//
// Exposes:
//   GET  /v1/runs/:run/stream   SSE read
//   POST /v1/runs/:run/ingest   NDJSON ingest
//   GET  /_health, /_readyz, /health   liveness / readiness
//   GET  /_metrics                     Prometheus scrape
//   OPTIONS *                          CORS preflight (204)
//
// The run path segment is for readable logs and metrics; the run-scoped JWT is
// the authority, so the handlers only check that it agrees with the token's run
// claim. team/task come from the verified token, not the URL.
//
// Wire protocol is byte-identical to the Python proxy (proxy.py) — Django and
// this Node service share the same Redis stream during the cutover window.

import { Hono } from 'hono'
import { stream } from 'hono/streaming'
import type { Redis } from 'ioredis'

import type { Config } from '../lib/config.js'
import { validateStreamReadToken, validateTaskPortForwardToken, validateTaskTerminalToken } from '../lib/jwt.js'
import { logger, type RequestLogger } from '../lib/logging.js'
import { getStreamKey } from '../lib/redis-stream.js'
import { StreamCapacity } from '../lib/stream-capacity.js'
import type { StreamReadTokenPayload, TaskPortForwardTokenPayload, TaskTerminalTokenPayload } from '../lib/types.js'
import { handleIngest } from './ingest-handler.js'
import { observeStreamConnectionRejected } from './metrics.js'
import { corsHeaders, corsPreflightHandler, httpMetrics, requestLog, securityHeaders } from './middleware.js'
import { registerPublicRoutes } from './public-routes.js'
import { streamTaskRunEvents } from './sse-handler.js'
import type { HonoCtx, HonoVariables, Lifecycle } from './types.js'

const PORT_FORWARD_AUTH_COOKIE = '__Host-ph_task_port_forward'
const MAX_PORT_FORWARD_REQUEST_BODY_BYTES = 10 * 1024 * 1024

// ---------------------------------------------------------------------------
// Exported types
// ---------------------------------------------------------------------------

export interface App {
    app: Hono<{ Variables: HonoVariables }>
    lifecycle: Lifecycle
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createApp(redis: Redis, config: Config, publicKeys: CryptoKey[]): App {
    const app = new Hono<{ Variables: HonoVariables }>()
    const lifecycle: Lifecycle = { shuttingDown: false }
    const streamCapacity = new StreamCapacity(config.maxConcurrentStreams, config.maxStreamsPerRun)

    app.onError((err, c) => {
        const requestLogger: RequestLogger | undefined = c.get('requestLogger')
        requestLogger?.extend({ error: err.message })
        logger.error('http.unhandled_error', {
            requestId: requestLogger?.id,
            method: c.req.method,
            path: new URL(c.req.url).pathname,
            error: err.message,
            stack: err.stack,
        })
        return c.json({ error: 'Internal server error' }, 500)
    })

    app.use('*', securityHeaders)
    app.use('*', corsHeaders(config))
    app.use('*', httpMetrics)
    app.use('*', requestLog)

    // -- CORS preflight --
    app.options('*', corsPreflightHandler(config))

    // -- Health, readiness, metrics --
    registerPublicRoutes(app, lifecycle, config.metricsToken)

    // -- SSE stream read --
    app.get('/v1/runs/:run/stream', async (c) => {
        // Token via Authorization: Bearer <token> only (no ?token= query param).
        const token = extractStreamReadToken(c)
        if (token === null) {
            return c.json({ error: 'Missing stream read token' }, 401)
        }

        let claims: StreamReadTokenPayload
        try {
            claims = await validateStreamReadToken(token, publicKeys)
        } catch (err: unknown) {
            const code = err instanceof Error ? err.constructor.name : 'UnknownError'
            return c.json({ error: 'Invalid stream read token', code }, 401)
        }

        const { run } = c.req.param() as { run: string }
        if (claims.runId !== run) {
            return c.json({ error: 'Token does not match run' }, 403)
        }

        const lastEventId = c.req.header('Last-Event-ID') ?? c.req.header('last-event-id') ?? null
        const startLatest = c.req.query('start') === 'latest'
        const streamKey = getStreamKey(claims.runId)

        // Reserve a concurrency slot before any Redis work; each accepted stream holds a
        // dedicated Redis connection until it closes. 503 (not 4xx) so clients reconnect
        // through their normal backoff instead of treating it as fatal.
        const rejection = streamCapacity.tryAcquire(claims.runId)
        if (rejection !== null) {
            observeStreamConnectionRejected(rejection)
            logger.warn('stream:rejected_capacity', { run, reason: rejection, open: streamCapacity.openTotal })
            c.header('Retry-After', '5')
            return c.json({ error: 'Too many concurrent stream connections' }, 503)
        }

        logger.info('stream:open', { run, lastEventId: lastEventId ?? undefined, startLatest })

        // The abort signal from the raw Request fires when the client disconnects.
        const signal = c.req.raw.signal

        return stream(c, async (responseStream) => {
            let chunks = 0
            const openedAt = Date.now()
            // Wire disconnect: when the client drops, abort the SSE generator.
            const generator = streamTaskRunEvents(streamKey, redis, {
                originProduct: 'unknown',
                lastEventId,
                startLatest,
            })

            // Race each generator chunk against the client-disconnect abort signal.
            // When abort fires we close the generator (its finally block records
            // the 'client_disconnect' metric outcome and cleans up Redis).
            const onAbort = (): void => {
                // Closing the response stream also causes the outer streaming()
                // wrapper to return, ending the handler.
                void generator.return(undefined)
            }

            signal.addEventListener('abort', onAbort, { once: true })

            try {
                // Set SSE-specific headers on the response.
                // Hono's stream() helper sets the response up before we write —
                // we mutate headers before writing the first byte.
                c.header('Content-Type', 'text/event-stream')
                c.header('Cache-Control', 'no-cache')
                c.header('X-Accel-Buffering', 'no')

                for await (const chunk of generator) {
                    if (signal.aborted) {
                        break
                    }
                    await responseStream.write(chunk)
                    chunks++
                    if (chunks === 1) {
                        logger.debug('stream:first-event', { run })
                    }
                }
            } finally {
                streamCapacity.release(claims.runId)
                signal.removeEventListener('abort', onAbort)
                // Ensure the generator's cleanup runs even if we broke early.
                await generator.return(undefined).catch(() => undefined)
                logger.info('stream:close', { run, chunks, ms: Date.now() - openedAt, aborted: signal.aborted })
            }
        })
    })

    // -- NDJSON event ingest --
    app.post('/v1/runs/:run/ingest', async (c) => {
        return handleIngest(c, redis, config, publicKeys)
    })

    const handlePortForwardAuth = async (c: HonoCtx, forwardId: string, mode: PortForwardMode): Promise<Response> => {
        const ticket = c.req.query('ticket') ?? ''
        const token = await exchangePortForwardTicket(config, ticket)
        if (token === null) {
            return c.json({ error: 'Invalid port forward ticket' }, 401)
        }

        let claims: TaskPortForwardTokenPayload
        try {
            claims = await validateTaskPortForwardToken(token, publicKeys)
        } catch (err: unknown) {
            const code = err instanceof Error ? err.constructor.name : 'UnknownError'
            return c.json({ error: 'Invalid port forward token', code }, 401)
        }
        if (claims.forwardId !== forwardId) {
            return c.json({ error: 'Token does not match port forward' }, 403)
        }

        const redirectPath = mode === 'host' ? '/' : `/v1/ports/${forwardId}/`
        c.header(
            'Set-Cookie',
            `${PORT_FORWARD_AUTH_COOKIE}=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=3600; Secure`
        )
        return c.redirect(redirectPath, 302)
    }

    // -- Authenticated task-run port previews --
    app.get('/auth/', async (c) => {
        const forwardId = previewForwardIdFromHost(c, config)
        if (forwardId === null) {
            return c.json({ error: 'Not found' }, 404)
        }
        return handlePortForwardAuth(c, forwardId, 'host')
    })

    app.get('/v1/ports/:forwardId/auth/', (c) => {
        return c.json({ error: 'Port preview auth requires an isolated preview host' }, 410)
    })

    const handlePortForward = async (c: HonoCtx, forwardId: string, mode: PortForwardMode): Promise<Response> => {
        const auth = extractPortForwardToken(c, { allowCookie: mode === 'host' })
        if (auth === null) {
            return c.json({ error: 'Missing port forward token' }, 401)
        }
        if (auth.source === 'cookie' && !isSamePreviewOriginRequest(c, config)) {
            return c.json({ error: 'Cross-origin port preview requests are not allowed' }, 403)
        }

        let claims: TaskPortForwardTokenPayload
        try {
            claims = await validateTaskPortForwardToken(auth.token, publicKeys)
        } catch (err: unknown) {
            const code = err instanceof Error ? err.constructor.name : 'UnknownError'
            return c.json({ error: 'Invalid port forward token', code }, 401)
        }
        if (claims.forwardId !== forwardId) {
            return c.json({ error: 'Token does not match port forward' }, 403)
        }

        const method = c.req.method.toUpperCase()
        let requestBody: ArrayBuffer | undefined
        if (method !== 'GET' && method !== 'HEAD') {
            const body = await readBoundedRequestBody(c.req.raw)
            if (body === null) {
                return c.json({ error: 'Port forward request body is too large' }, 413)
            }
            requestBody = body
        }

        const resolved = await resolvePortForward(config, auth.token)
        if (resolved === null) {
            return c.json({ error: 'Port forward is not available' }, 404)
        }
        if (resolved.port !== claims.port || resolved.forward_id !== claims.forwardId) {
            return c.json({ error: 'Resolved port forward does not match token' }, 403)
        }

        const upstreamUrl = buildSandboxPortUrl(c.req.url, forwardId, resolved, config, mode)
        if (upstreamUrl === null) {
            return c.json({ error: 'Port forward target is not available' }, 502)
        }
        const headers = filteredProxyHeaders(c.req.raw.headers)
        headers.set('Authorization', `Bearer ${resolved.connection_token}`)

        // Propagate client cancellation to the upstream fetch so a closed browser tab
        // frees the sandbox connection immediately. We deliberately do NOT impose a
        // response timeout: previews target dev servers whose HMR/SSE streams are
        // legitimately long-lived, and a blanket timeout would kill them. A global
        // in-flight ceiling for genuine abuse belongs at the ingress/LB, not per-request.
        const init: RequestInit = { method, headers, redirect: 'manual', signal: c.req.raw.signal }
        if (requestBody !== undefined) {
            init.body = requestBody
        }

        try {
            const upstream = await fetch(upstreamUrl, init)
            return new Response(upstream.body, {
                status: upstream.status,
                statusText: upstream.statusText,
                headers: filteredResponseHeaders(upstream.headers, forwardId, resolved, mode),
            })
        } catch (err) {
            logger.warn('port_forward:upstream_unreachable', {
                forwardId,
                run: claims.runId,
                error: err instanceof Error ? err.message : String(err),
            })
            return c.json({ error: 'Port forward target is not reachable' }, 502)
        }
    }

    app.all('/v1/ports/:forwardId', (c) => {
        const { forwardId } = c.req.param() as { forwardId: string }
        return handlePortForward(c, forwardId, 'path')
    })
    app.all('/v1/ports/:forwardId/*', (c) => {
        const { forwardId } = c.req.param() as { forwardId: string }
        return handlePortForward(c, forwardId, 'path')
    })

    const handleTerminal = async (c: HonoCtx, suffix: TerminalProxySuffix): Promise<Response> => {
        const token = extractStreamReadToken(c)
        if (token === null) {
            return c.json({ error: 'Missing terminal token' }, 401)
        }

        let claims: TaskTerminalTokenPayload
        try {
            claims = await validateTaskTerminalToken(token, publicKeys)
        } catch (err: unknown) {
            const code = err instanceof Error ? err.constructor.name : 'UnknownError'
            return c.json({ error: 'Invalid terminal token', code }, 401)
        }

        const { run, terminalId } = c.req.param() as { run: string; terminalId: string }
        if (claims.runId !== run || claims.terminalId !== terminalId) {
            return c.json({ error: 'Token does not match terminal' }, 403)
        }

        const method = c.req.method.toUpperCase()
        let requestBody: ArrayBuffer | undefined
        if (method !== 'GET' && method !== 'HEAD') {
            const body = await readBoundedRequestBody(c.req.raw)
            if (body === null) {
                return c.json({ error: 'Terminal request body is too large' }, 413)
            }
            requestBody = body
        }

        const resolved = await resolveTerminal(config, token)
        if (resolved === null) {
            return c.json({ error: 'Terminal is not available' }, 404)
        }
        if (resolved.terminal_id !== claims.terminalId || resolved.run_id !== claims.runId) {
            return c.json({ error: 'Resolved terminal does not match token' }, 403)
        }

        const upstreamUrl = buildSandboxTerminalUrl(terminalId, suffix, resolved, config)
        if (upstreamUrl === null) {
            return c.json({ error: 'Terminal target is not available' }, 502)
        }

        const headers = filteredProxyHeaders(c.req.raw.headers)
        headers.set('Authorization', `Bearer ${resolved.connection_token}`)
        const init: RequestInit = { method, headers, redirect: 'manual' }
        if (requestBody !== undefined) {
            init.body = requestBody
        }

        try {
            const upstream = await fetch(upstreamUrl, init)
            return new Response(upstream.body, {
                status: upstream.status,
                statusText: upstream.statusText,
                headers: filteredTerminalResponseHeaders(upstream.headers),
            })
        } catch (err) {
            logger.warn('terminal:upstream_unreachable', {
                terminalId,
                run: claims.runId,
                error: err instanceof Error ? err.message : String(err),
            })
            return c.json({ error: 'Terminal target is not reachable' }, 502)
        }
    }

    app.post('/v1/runs/:run/terminals/:terminalId', (c) => handleTerminal(c, ''))
    app.get('/v1/runs/:run/terminals/:terminalId/stream', (c) => handleTerminal(c, '/stream'))
    app.post('/v1/runs/:run/terminals/:terminalId/input', (c) => handleTerminal(c, '/input'))
    app.post('/v1/runs/:run/terminals/:terminalId/resize', (c) => handleTerminal(c, '/resize'))
    app.delete('/v1/runs/:run/terminals/:terminalId', (c) => handleTerminal(c, ''))

    // -- Catch-all 404 --
    app.all('*', (c) => {
        const forwardId = previewForwardIdFromHost(c, config)
        if (forwardId !== null) {
            return handlePortForward(c, forwardId, 'host')
        }
        return c.json({ error: 'Not found' }, 404)
    })

    return { app, lifecycle }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

// Extract the bearer token for the stream-read leg from the Authorization
// header only. There is deliberately no ?token= query fallback: query strings
// are recorded by upstream infrastructure (load balancers, reverse proxies,
// CDNs, WAFs) even though the app logger strips them, which would leak the
// run-scoped JWT into access logs. Every client sends Authorization: Bearer
// (the browser uses fetch-event-source, not native EventSource), so the header
// is sufficient. If a native-EventSource client is ever needed, add a
// single-use ticket-exchange endpoint rather than putting the JWT in the URL.
function extractStreamReadToken(c: { req: { header: (name: string) => string | undefined } }): string | null {
    const authorization = c.req.header('Authorization') ?? c.req.header('authorization')
    if (!authorization) {
        return null
    }
    const prefix = 'Bearer '
    if (!authorization.startsWith(prefix)) {
        return null
    }
    const token = authorization.slice(prefix.length).trim()
    return token || null
}

interface ExtractedPortForwardToken {
    token: string
    source: 'bearer' | 'cookie'
}

function extractPortForwardToken(
    c: { req: { header: (name: string) => string | undefined } },
    { allowCookie }: { allowCookie: boolean }
): ExtractedPortForwardToken | null {
    const bearer = extractStreamReadToken(c)
    if (bearer) {
        return { token: bearer, source: 'bearer' }
    }
    if (!allowCookie) {
        return null
    }
    const cookie = c.req.header('Cookie') ?? c.req.header('cookie') ?? ''
    const pathCookie = cookie
        .split(';')
        .map((part) => part.trim())
        .find((part) => part.startsWith(`${PORT_FORWARD_AUTH_COOKIE}=`))
    if (!pathCookie) {
        return null
    }
    const token = decodeURIComponent(pathCookie.slice(PORT_FORWARD_AUTH_COOKIE.length + 1))
    return token ? { token, source: 'cookie' } : null
}

interface ResolvedPortForward {
    run_id: string
    task_id: string
    team_id: number
    forward_id: string
    port: number
    sandbox_url: string
    connection_token: string
    sandbox_connect_token?: string | null
}

type PortForwardMode = 'host' | 'path'

interface ResolvedTerminal {
    run_id: string
    task_id: string
    team_id: number
    terminal_id: string
    sandbox_url: string
    connection_token: string
    sandbox_connect_token?: string | null
}

type TerminalProxySuffix = '' | '/stream' | '/input' | '/resize'

function isSamePreviewOriginRequest(c: HonoCtx, config: Config): boolean {
    const expectedOrigin = previewOriginFromHost(c, config)
    if (expectedOrigin === null) {
        return false
    }

    const secFetchSite = c.req.header('Sec-Fetch-Site') ?? c.req.header('sec-fetch-site')
    if (secFetchSite && !['same-origin', 'none'].includes(secFetchSite.toLowerCase())) {
        return false
    }

    const origin = c.req.header('Origin') ?? c.req.header('origin')
    if (origin && normalizeOrigin(origin) !== expectedOrigin) {
        return false
    }

    const referer = c.req.header('Referer') ?? c.req.header('referer')
    if (referer) {
        const refererOrigin = normalizeOrigin(referer)
        if (refererOrigin === null || refererOrigin !== expectedOrigin) {
            return false
        }
    }

    return true
}

function previewForwardIdFromHost(c: HonoCtx, config: Config): string | null {
    const previewHost = previewHostFromRequest(c, config)
    if (previewHost === null) {
        return null
    }
    const { previewHostname, publicHostname } = previewHost
    const suffix = `.${publicHostname}`
    const forwardId = previewHostname.slice(0, -suffix.length)
    if (!forwardId || forwardId.includes('.')) {
        return null
    }
    return forwardId
}

function previewOriginFromHost(c: HonoCtx, config: Config): string | null {
    const previewHost = previewHostFromRequest(c, config)
    if (previewHost === null) {
        return null
    }
    const { publicUrl, requestUrl } = previewHost
    const port = requestUrl.port ? `:${requestUrl.port}` : ''
    return `${publicUrl.protocol}//${requestUrl.hostname.toLowerCase()}${port}`
}

interface PreviewHost {
    publicUrl: URL
    requestUrl: URL
    previewHostname: string
    publicHostname: string
}

function previewHostFromRequest(c: HonoCtx, config: Config): PreviewHost | null {
    if (!config.tasksAgentProxyPublicUrl) {
        return null
    }
    let publicUrl: URL
    try {
        publicUrl = new URL(config.tasksAgentProxyPublicUrl)
    } catch {
        return null
    }

    const hostHeader = c.req.header('Host') ?? c.req.header('host') ?? new URL(c.req.url).host
    let requestUrl: URL
    try {
        requestUrl = new URL(`http://${hostHeader}`)
    } catch {
        return null
    }
    const previewHostname = requestUrl.hostname.toLowerCase()
    const publicHostname = publicUrl.hostname.toLowerCase()
    const suffix = `.${publicHostname}`
    if (!previewHostname.endsWith(suffix) || previewHostname === publicHostname) {
        return null
    }
    // Compare effective ports so a request to an unexpected explicit port can't slip
    // through when the public URL relies on the scheme default (e.g. prod https with no
    // port would otherwise skip the check and accept <id>.<host>:8080).
    const defaultPort = publicUrl.protocol === 'https:' ? '443' : '80'
    const publicPort = publicUrl.port || defaultPort
    const requestPort = requestUrl.port || defaultPort
    if (publicPort !== requestPort) {
        return null
    }

    return { publicUrl, requestUrl, previewHostname, publicHostname }
}

function normalizeOrigin(rawUrl: string): string | null {
    let url: URL
    try {
        url = new URL(rawUrl)
    } catch {
        return null
    }
    return `${url.protocol}//${url.hostname.toLowerCase()}${url.port ? `:${url.port}` : ''}`
}

async function readBoundedRequestBody(request: Request): Promise<ArrayBuffer | null> {
    const contentLength = request.headers.get('content-length')
    if (contentLength) {
        const parsed = Number(contentLength)
        if (!Number.isFinite(parsed) || parsed > MAX_PORT_FORWARD_REQUEST_BODY_BYTES) {
            return null
        }
    }

    if (request.body === null) {
        return new ArrayBuffer(0)
    }

    const reader = request.body.getReader()
    const chunks: Uint8Array[] = []
    let size = 0
    try {
        while (true) {
            const { done, value } = await reader.read()
            if (done) {
                break
            }
            size += value.byteLength
            if (size > MAX_PORT_FORWARD_REQUEST_BODY_BYTES) {
                await reader.cancel()
                return null
            }
            chunks.push(value)
        }
    } finally {
        reader.releaseLock()
    }

    const body = new Uint8Array(size)
    let offset = 0
    for (const chunk of chunks) {
        body.set(chunk, offset)
        offset += chunk.byteLength
    }
    return body.buffer
}

async function exchangePortForwardTicket(config: Config, ticket: string): Promise<string | null> {
    if (!ticket || !config.djangoCallbackBaseUrl) {
        logger.warn('port_forward:ticket_exchange_unconfigured')
        return null
    }
    const response = await fetch(`${config.djangoCallbackBaseUrl}/internal/tasks/port-forward/exchange-ticket/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Agent-Proxy-Secret': config.agentProxyCallbackSecret,
        },
        body: JSON.stringify({ ticket }),
    })
    if (!response.ok) {
        logger.warn('port_forward:ticket_exchange_failed', { status: response.status })
        return null
    }
    const payload = (await response.json()) as { token?: unknown }
    return typeof payload.token === 'string' && payload.token ? payload.token : null
}

async function resolvePortForward(config: Config, token: string): Promise<ResolvedPortForward | null> {
    if (!config.djangoCallbackBaseUrl) {
        logger.warn('port_forward:resolve_unconfigured')
        return null
    }
    const response = await fetch(`${config.djangoCallbackBaseUrl}/internal/tasks/port-forward/resolve/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Agent-Proxy-Secret': config.agentProxyCallbackSecret,
        },
        body: JSON.stringify({ token }),
    })
    if (!response.ok) {
        logger.warn('port_forward:resolve_failed', { status: response.status })
        return null
    }
    return (await response.json()) as ResolvedPortForward
}

async function resolveTerminal(config: Config, token: string): Promise<ResolvedTerminal | null> {
    if (!config.djangoCallbackBaseUrl) {
        logger.warn('terminal:resolve_unconfigured')
        return null
    }
    const response = await fetch(`${config.djangoCallbackBaseUrl}/internal/tasks/terminal/resolve/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Agent-Proxy-Secret': config.agentProxyCallbackSecret,
        },
        body: JSON.stringify({ token }),
    })
    if (!response.ok) {
        logger.warn('terminal:resolve_failed', { status: response.status })
        return null
    }
    return (await response.json()) as ResolvedTerminal
}

function buildSandboxPortUrl(
    requestUrl: string,
    forwardId: string,
    resolved: ResolvedPortForward,
    config: Config,
    mode: PortForwardMode
): string | null {
    const sandboxBaseUrl = parseAllowedSandboxUrl(resolved.sandbox_url, config)
    if (sandboxBaseUrl === null) {
        logger.warn('port_forward:invalid_sandbox_url', { forwardId, run: resolved.run_id })
        return null
    }
    const incoming = new URL(requestUrl)
    const prefix = `/v1/ports/${forwardId}`
    const suffix =
        mode === 'host'
            ? incoming.pathname || '/'
            : incoming.pathname.startsWith(prefix)
              ? incoming.pathname.slice(prefix.length) || '/'
              : '/'
    const target = new URL(`/ports/${resolved.port}${suffix}`, sandboxBaseUrl)
    incoming.searchParams.forEach((value, key) => {
        target.searchParams.append(key, value)
    })
    if (resolved.sandbox_connect_token) {
        target.searchParams.set('_modal_connect_token', resolved.sandbox_connect_token)
    }
    return target.toString()
}

function buildSandboxTerminalUrl(
    terminalId: string,
    suffix: TerminalProxySuffix,
    resolved: ResolvedTerminal,
    config: Config
): string | null {
    const sandboxBaseUrl = parseAllowedSandboxUrl(resolved.sandbox_url, config)
    if (sandboxBaseUrl === null) {
        logger.warn('terminal:invalid_sandbox_url', { terminalId, run: resolved.run_id })
        return null
    }
    const target = new URL(`/terminals/${encodeURIComponent(terminalId)}${suffix}`, sandboxBaseUrl)
    if (resolved.sandbox_connect_token) {
        target.searchParams.set('_modal_connect_token', resolved.sandbox_connect_token)
    }
    return target.toString()
}

function parseAllowedSandboxUrl(rawUrl: string, config: Config): URL | null {
    let url: URL
    try {
        url = new URL(rawUrl)
    } catch {
        return null
    }
    if (url.protocol === 'https:' && url.hostname.endsWith('.modal.run')) {
        return url
    }
    const isLocalHost = url.hostname === 'localhost' || url.hostname === '127.0.0.1'
    if (url.protocol === 'http:' && isLocalHost && isLocalDjangoCallback(config.djangoCallbackBaseUrl)) {
        return url
    }
    return null
}

function isLocalDjangoCallback(rawUrl: string): boolean {
    if (!rawUrl) {
        return true
    }
    try {
        const url = new URL(rawUrl)
        return url.hostname === 'localhost' || url.hostname === '127.0.0.1'
    } catch {
        return false
    }
}

const HOP_BY_HOP_HEADERS = new Set([
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailer',
    'transfer-encoding',
    'upgrade',
])

function filteredProxyHeaders(input: Headers): Headers {
    const headers = new Headers()
    input.forEach((value, key) => {
        const normalized = key.toLowerCase()
        if (
            HOP_BY_HOP_HEADERS.has(normalized) ||
            normalized === 'host' ||
            normalized === 'authorization' ||
            normalized === 'cookie'
        ) {
            return
        }
        headers.set(key, value)
    })
    return headers
}

function filteredResponseHeaders(
    input: Headers,
    forwardId: string,
    resolved: ResolvedPortForward,
    mode: PortForwardMode
): Headers {
    const headers = new Headers()
    input.forEach((value, key) => {
        const normalized = key.toLowerCase()
        if (HOP_BY_HOP_HEADERS.has(normalized) || normalized === 'service-worker-allowed') {
            return
        }
        if (normalized === 'location') {
            headers.set(key, rewritePortForwardLocation(value, forwardId, resolved, mode))
            return
        }
        headers.set(key, value)
    })
    return headers
}

function filteredTerminalResponseHeaders(input: Headers): Headers {
    const headers = new Headers()
    input.forEach((value, key) => {
        const normalized = key.toLowerCase()
        if (HOP_BY_HOP_HEADERS.has(normalized) || normalized === 'service-worker-allowed') {
            return
        }
        headers.set(key, value)
    })
    return headers
}

function rewritePortForwardLocation(
    value: string,
    forwardId: string,
    resolved: ResolvedPortForward,
    mode: PortForwardMode
): string {
    const prefix = `/v1/ports/${forwardId}`
    if (value.startsWith('/') && !value.startsWith('//')) {
        return mode === 'host' ? value : `${prefix}${value}`
    }
    let location: URL
    try {
        location = new URL(value)
    } catch {
        return value
    }
    const isLoopback = location.hostname === 'localhost' || location.hostname === '127.0.0.1'
    if (!isLoopback || effectiveUrlPort(location) !== resolved.port) {
        return value
    }
    const locationPath = `${location.pathname}${location.search}${location.hash}`
    return mode === 'host' ? locationPath : `${prefix}${locationPath}`
}

function effectiveUrlPort(url: URL): number | null {
    if (url.port) {
        return Number(url.port)
    }
    if (url.protocol === 'http:') {
        return 80
    }
    if (url.protocol === 'https:') {
        return 443
    }
    return null
}
