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
import { validateStreamReadToken } from '../lib/jwt.js'
import { logger, type RequestLogger } from '../lib/logging.js'
import { getStreamKey } from '../lib/redis-stream.js'
import { StreamCapacity } from '../lib/stream-capacity.js'
import type { StreamReadTokenPayload } from '../lib/types.js'
import { handleIngest } from './ingest-handler.js'
import { observeStreamConnectionRejected } from './metrics.js'
import { corsHeaders, corsPreflightHandler, httpMetrics, requestLog, securityHeaders } from './middleware.js'
import { registerPublicRoutes } from './public-routes.js'
import { streamTaskRunEvents } from './sse-handler.js'
import type { HonoVariables, Lifecycle } from './types.js'

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

    // -- Catch-all 404 --
    app.all('*', (c) => c.json({ error: 'Not found' }, 404))

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
