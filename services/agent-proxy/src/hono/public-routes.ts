// Probe, health and metrics routes for the agent-proxy.
//
// These paths are excluded from the request log so Kubernetes health checks
// don't drown out real traffic.
//
// /_metrics optionally requires a bearer token (AGENT_PROXY_METRICS_TOKEN):
// this host is publicly reachable for the SSE/ingest routes, so operational
// metrics should not be open to the internet once the scrape token is
// provisioned. Unset keeps the route open for in-cluster scrapes that have
// no token configured.

import type { Env, Hono } from 'hono'
import { createHash, timingSafeEqual } from 'node:crypto'

import { register, shuttingDown as shuttingDownGauge } from './metrics.js'
import type { Lifecycle } from './types.js'

// Paths excluded from the request log middleware.
export const PROBE_PATHS = new Set(['/_health', '/_readyz', '/_metrics', '/health'])

// Hash both sides so timingSafeEqual gets equal-length buffers without leaking
// the configured token's length through an early mismatch return.
function tokensMatch(provided: string, expected: string): boolean {
    const providedDigest = createHash('sha256').update(provided).digest()
    const expectedDigest = createHash('sha256').update(expected).digest()
    return timingSafeEqual(providedDigest, expectedDigest)
}

export function registerPublicRoutes<E extends Env>(app: Hono<E>, lifecycle: Lifecycle, metricsToken: string): void {
    app.get('/_health', (c) => c.json({ status: 'ok' }))

    app.get('/_readyz', (c) => {
        if (lifecycle.shuttingDown) {
            return c.json({ status: 'shutting_down' }, 503)
        }
        return c.json({ status: 'ok' })
    })

    app.get('/health', (c) => c.json({ status: 'ok' }))

    app.get('/_metrics', async (c) => {
        if (metricsToken) {
            const authorization = c.req.header('Authorization') ?? ''
            const provided = authorization.startsWith('Bearer ') ? authorization.slice('Bearer '.length).trim() : ''
            if (!provided || !tokensMatch(provided, metricsToken)) {
                return c.json({ error: 'Unauthorized' }, 401)
            }
        }

        // Update shutting-down gauge inline so it reflects the current state
        // when the scrape runs (no event-loop delays on the gauge itself).
        shuttingDownGauge.set(lifecycle.shuttingDown ? 1 : 0)
        const metrics = await register.metrics()
        return c.text(metrics, 200, { 'Content-Type': register.contentType })
    })
}
