// HTTP surface. One functional route: the request scope lives entirely in the JWT, so
// `resolve` takes no body (see auth/jwt.ts). It is a POST so no intermediary treats a
// secret response as cacheable.

import { Hono } from 'hono'

import { bearerToken, type JwtVerifier } from '../auth/jwt'
import { AuthError } from '../auth/types'
import { logger } from '../lib/logging'
import { authFailuresTotal, httpRequestDurationSeconds, httpRequestsTotal } from '../metrics'
import { resolveKeys } from '../resolve'
import type { Lifecycle, MountedSecrets } from '../types'

export interface AppOptions {
    verifier: JwtVerifier
    lifecycle: Lifecycle
    secrets: () => MountedSecrets | null
}

export function createApp(opts: AppOptions): Hono {
    const app = new Hono()

    app.use('*', async (c, next) => {
        const start = performance.now()
        try {
            await next()
        } finally {
            // The registered route pattern, not the raw path: an unmatched request labels
            // as the router's catch-all, so nobody can grow the series set with URLs.
            const labels = { method: c.req.method, route: c.req.routePath, status: String(c.res.status) }
            httpRequestsTotal.labels(labels).inc()
            httpRequestDurationSeconds.labels(labels).observe((performance.now() - start) / 1000)
        }
    })

    app.get('/_liveness', (c) => c.json({ status: 'ok' }))

    // Not ready until the pod holds secrets: one that does not would answer every
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
        // service into what looks like a deleted secret. A failed re-read keeps the
        // secrets already held and never lands here.
        const mounted = opts.secrets()
        if (!mounted) {
            logger.error('resolve:no_secrets_held', { deployment: identity.deployment })
            return c.json({ error: 'Secret store unavailable' }, 503)
        }

        return c.json(resolveKeys(identity, mounted))
    })

    return app
}
