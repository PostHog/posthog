// HTTP surface.
//
// One functional route. The request scope lives entirely in the JWT, so `resolve`
// takes no body — see auth/jwt.ts for why. Keeping it a POST (rather than a GET) means
// no intermediary treats a credential response as cacheable.

import { Hono } from 'hono'
import { createHash, timingSafeEqual } from 'node:crypto'

import { bearerToken, type JwtVerifier } from '../auth/jwt.js'
import { AuthError } from '../auth/types.js'
import { logger } from '../lib/logging.js'
import { authFailuresTotal, httpRequestDurationSeconds, httpRequestsTotal, register, shuttingDown } from '../metrics.js'
import { resolveKeys, type ResolveDeps } from '../policy/resolve.js'

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

// Route label for metrics. Every path here is static, so this only exists to keep an
// unmatched request from creating an unbounded label value.
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

    // Not ready until the client registry is loaded and every provider has been warmed
    // once. A pod that cannot reach Secrets Manager should fail its probe rather than
    // accept traffic it will have to error on.
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
            // A cold miss with a broken store. Everything softer than this — a stale
            // snapshot, an unreadable Redis entry — has already degraded gracefully by
            // the time it reaches here.
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
