// HTTP surface. One functional route: the request scope lives entirely in the JWT, so
// `resolve` takes no body (see auth/jwt.ts). It is a POST so no intermediary treats a
// credential response as cacheable.

import { Hono } from 'hono'
import { createHash, timingSafeEqual } from 'node:crypto'

import { bearerToken, type JwtVerifier } from '../auth/jwt'
import { AuthError } from '../auth/types'
import { logger } from '../lib/logging'
import { authFailuresTotal, httpRequestDurationSeconds, httpRequestsTotal, register, shuttingDown } from '../metrics'
import { resolveKeys } from '../resolve'
import type { Lifecycle, MountedCredentials } from '../types'
import type { UsageRecorder } from '../usage/recorder'

const KNOWN_PATHS = new Set(['/_liveness', '/_readiness', '/metrics', '/v1/secrets/resolve'])

// Hash both sides so timingSafeEqual gets equal-length buffers without leaking the
// configured token's length through an early mismatch return.
function tokensMatch(provided: string, expected: string): boolean {
    return timingSafeEqual(
        createHash('sha256').update(provided).digest(),
        createHash('sha256').update(expected).digest()
    )
}

export interface AppOptions {
    verifier: JwtVerifier
    lifecycle: Lifecycle
    credentials: () => MountedCredentials | null
    recorder: UsageRecorder
    metricsToken: string
}

export function createApp(opts: AppOptions): Hono {
    const app = new Hono()

    app.use('*', async (c, next) => {
        const pathname = new URL(c.req.url).pathname
        // An unmatched path must not become a label value, or anyone can grow the series set.
        const route = KNOWN_PATHS.has(pathname) ? pathname : 'other'
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

    // Not ready until the pod holds credentials: one that does not would answer every
    // resolve all-missing, which callers treat as terminal rather than retryable.
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
            const header = c.req.header('Authorization')
            const provided = header?.startsWith('Bearer ') ? header.slice('Bearer '.length).trim() : ''
            if (!provided || !tokensMatch(provided, opts.metricsToken)) {
                return c.json({ error: 'Unauthorized' }, 401)
            }
        }
        shuttingDown.set(opts.lifecycle.shuttingDown ? 1 : 0)
        return c.text(await register.metrics(), 200, { 'Content-Type': register.contentType })
    })

    app.post('/v1/secrets/resolve', async (c) => {
        let identity
        try {
            identity = await opts.verifier.verify(bearerToken(c.req.header('Authorization')))
        } catch (err) {
            if (err instanceof AuthError) {
                authFailuresTotal.labels({ reason: err.reason }).inc()
                logger.warn('auth:rejected', { reason: err.reason })
                return c.json({ error: 'Unauthorized' }, 401)
            }
            throw err
        }

        // Never answered as an all-`missing` response: a caller treats a missing key as
        // terminal, so answering that way during a cold start would turn an unavailable
        // service into what looks like a deleted credential. A failed re-read keeps the
        // credentials already held and never lands here.
        const mounted = opts.credentials()
        if (!mounted) {
            logger.error('secrets:no_credentials_held', { deployment: identity.deployment })
            return c.json({ error: 'Secret store unavailable' }, 503)
        }

        return c.json(resolveKeys(identity, mounted, opts.recorder))
    })

    return app
}
