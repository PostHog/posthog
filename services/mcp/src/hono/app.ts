import { Hono } from 'hono'

import { attachRedis, corsMiddleware, securityHeaders } from './middleware'
import { registerPublicRoutes } from './public-routes'
import { SessionStore } from './session-store'
import { StreamableMcpHandler } from './streamable-handler'
import type { HonoEnv, RedisWithPing } from './types'

/**
 * Composition root for the Hono MCP server.
 *
 * Layout:
 *   - `middleware.ts`         security headers, CORS, redis injection
 *   - `public-routes.ts`      landing, health, OAuth metadata, redirects, UI app static
 *   - `streamable-handler.ts` `/mcp` (Streamable HTTP transport — the only transport
 *                             we serve; SSE was dropped because its long-lived TCP
 *                             stream would force pod-pinning at the ingress)
 *   - `session-store.ts`      in-memory transport registry with TTL + pod cap
 *   - `request-utils.ts`      auth + error helpers
 */
export function createApp(redis: RedisWithPing): Hono<HonoEnv> {
    const app = new Hono<HonoEnv>()
    const store = new SessionStore()

    app.use('*', securityHeaders)
    app.use('*', corsMiddleware)
    app.use('*', attachRedis(redis))

    registerPublicRoutes(app, redis)

    const streamable = new StreamableMcpHandler(redis, store)
    app.all('/mcp', streamable.fetch)
    app.all('/mcp/*', streamable.fetch)

    app.all('*', (c) => c.notFound())
    return app
}
