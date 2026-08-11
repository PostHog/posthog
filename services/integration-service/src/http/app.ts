// HTTP surface. One functional route: the request scope lives entirely in the JWT, so
// `resolve` takes no body (see auth/jwt.ts). It is a POST so no intermediary treats a
// credential response as cacheable.

import { Hono } from 'hono'
import { createHash, timingSafeEqual } from 'node:crypto'

import { bearerToken, type JwtVerifier } from '../auth/jwt'
import { AuthError } from '../auth/types'
import { logger } from '../lib/logging'
import { authFailuresTotal, httpRequestDurationSeconds, httpRequestsTotal, register, shuttingDown } from '../metrics'
import { resolveKeys, type ResolveDeps } from '../policy/resolve'

export const RESOLVE_PATH = '/v1/secrets/resolve'

export interface Lifecycle {
    shuttingDown: boolean
    ready: boolean
}

const PROBE_PATHS = new Set(['/_liveness', '/_readiness', '/metrics'])

// Hash both sides so timingSafeEqual gets equal-length buffers without leaking the
// configured token's length through an early mismatch return.
function tokensMatch(provided: string, expected: string): boolean {
    return timingSafeEqual(
        createHash('sha256').update(provided).digest(),
        createHash('sha256').update(expected).digest()
    )
}

// Keeps an unmatched request from creating an unbounded metric label value.
function routeLabel(pathname: string): string {
    return PROBE_PATHS.has(pathname) || pathname === RESOLVE_PATH ? pathname : 'other'
}

export interface AppOptions {
    verifier: JwtVerifier
    lifecycle: Lifecycle
    resolveDeps: ResolveDeps
    metricsToken: string
}

export function createApp(opts: AppOptions): Hono {
    const app = new Hono()

    app.use('*', async (c, next) => {
        const route = routeLabel(new URL(c.req.url).pathname)
        const start = performance.now()
        try {
            await next()
        } finally {
            const labels = { method: c.req.method, route, status: String(c.res.status) }
            httpRequestsTotal.labels(labels).inc()
            httpRequestDurationSeconds.labels(labels).observe((performance.now() - start) / 1000)
        }
    })

    app.get('/_liveness', (c) => c.json({ status: 'ok' }))

    // Not ready until the pod holds a credential snapshot: one that does not would answer
    // every resolve all-missing, which callers treat as terminal rather than retryable.
    app.get('/_readiness', (c) => {
        if (opts.lifecycle.shuttingDown) {
            return c.json({ status: 'shutting_down' }, 503)
        }
        if (!opts.lifecycle.ready) {
            return c.json({ status: 'starting' }, 503)
        }
        return c.json({ status: 'ok' })
    })

    app.get('/metrics', async (c) => {
        if (opts.metricsToken) {
            const provided = bearerOrEmpty(c.req.header('Authorization'))
            if (!provided || !tokensMatch(provided, opts.metricsToken)) {
                return c.json({ error: 'Unauthorized' }, 401)
            }
        }
        shuttingDown.set(opts.lifecycle.shuttingDown ? 1 : 0)
        return c.text(await register.metrics(), 200, { 'Content-Type': register.contentType })
    })

    app.post(RESOLVE_PATH, async (c) => {
        let verified
        try {
            verified = await opts.verifier.verify(bearerToken(c.req.header('Authorization')))
        } catch (err) {
            if (err instanceof AuthError) {
                authFailuresTotal.labels({ reason: err.reason }).inc()
                logger.warn('auth:rejected', { reason: err.reason })
                return c.json({ error: 'Unauthorized' }, 401)
            }
            throw err
        }

        try {
            const response = await resolveKeys(verified, opts.resolveDeps)
            return c.json(response)
        } catch (err) {
            // Reaching here means the pod has never held a snapshot; a failed re-read
            // keeps the previous one and never lands here.
            logger.error('secrets:resolve_failed', {
                deployment: verified.deployment,
                error: err instanceof Error ? err.message : String(err),
            })
            return c.json({ error: 'Secret store unavailable' }, 503)
        }
    })

    return app
}

function bearerOrEmpty(header: string | undefined): string {
    return header?.startsWith('Bearer ') ? header.slice('Bearer '.length).trim() : ''
}
