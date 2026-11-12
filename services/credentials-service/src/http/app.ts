// HTTP surface. For platform secrets the request scope lives entirely in the JWT, so
// `resolve` takes no body (see auth/jwt.ts). It is a POST so no intermediary treats a
// secret response as cacheable. The integration routes are in ./integrations.ts.

import { Hono } from 'hono'

import type { IntegrationVerifier } from '../auth/integrations'
import { bearerToken, type JwtVerifier } from '../auth/jwt'
import { AuthError } from '../auth/types'
import type { IntegrationsService } from '../integrations/service'
import { logger } from '../lib/logging'
import { authFailuresTotal, httpRequestDurationSeconds, httpRequestsTotal } from '../metrics'
import { resolveKeys } from '../resolve'
import type { Lifecycle, MountedSecrets } from '../types'
import { createIntegrationRoutes } from './integrations'

export interface AppOptions {
    verifier: JwtVerifier
    lifecycle: Lifecycle
    secrets: () => MountedSecrets | null
    /**
     * The integration routes. A getter lets the server turn them on after boot, when the database
     * answers late. While it returns undefined, every integration path answers 404.
     */
    integrations?: IntegrationDeps | (() => IntegrationDeps | undefined)
}

export interface IntegrationDeps {
    verifier: IntegrationVerifier
    service: IntegrationsService
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

    const integrations = opts.integrations
    if (integrations) {
        let routes: { deps: IntegrationDeps; app: ReturnType<typeof createIntegrationRoutes> } | undefined
        // `mount` strips the prefix, so the routes keep their own paths. The default request
        // copy passes the Node server request as `RequestInit`, which Node 26 rejects.
        const stripPrefix = (request: Request): Request => {
            const url = new URL(request.url)
            url.pathname = url.pathname.slice('/v1/integrations'.length) || '/'
            const hasBody = request.method !== 'GET' && request.method !== 'HEAD'
            return new Request(url, {
                method: request.method,
                headers: request.headers,
                body: hasBody ? request.body : null,
                duplex: 'half',
            } as RequestInit)
        }
        app.mount(
            '/v1/integrations',
            async (request) => {
                const deps = typeof integrations === 'function' ? integrations() : integrations
                if (!deps) {
                    return new Response('404 Not Found', { status: 404 })
                }
                const current = routes?.deps === deps ? routes : (routes = { deps, app: createIntegrationRoutes(deps) })
                return current.app.fetch(request)
            },
            { replaceRequest: stripPrefix }
        )
    }

    return app
}
