import { Hono } from 'hono'

import { attachRedis, corsMiddleware, securityHeaders } from './middleware'
import { registerPublicRoutes } from './public-routes'
import { SessionStore } from './session-store'
import { SseMcpHandler } from './sse-handler'
import { StreamableMcpHandler } from './streamable-handler'
import type { HonoEnv, RedisWithPing } from './types'

/**
 * Composition root for the Hono MCP server.
 *
 * Layout:
 *   - `middleware.ts`         security headers, CORS, redis injection
 *   - `public-routes.ts`      landing, health, OAuth metadata, redirects, UI app static
 *   - `streamable-handler.ts` `/mcp` (Streamable HTTP transport)
 *   - `sse-handler.ts`        `/sse` (Server-Sent Events transport)
 *   - `session-store.ts`      in-memory transport registries with TTL + pod cap
 *   - `request-utils.ts`      auth + error helpers shared between transports
 */
export function createApp(redis: RedisWithPing): Hono<HonoEnv> {
    const app = new Hono<HonoEnv>()
    const store = new SessionStore()

    app.use('*', securityHeaders)
    app.use('*', corsMiddleware)
    app.use('*', attachRedis(redis))

    registerPublicRoutes(app, redis)

    const streamable = new StreamableMcpHandler(redis, store)
    const sse = new SseMcpHandler(redis, store)
    app.all('/mcp', streamable.fetch)
    app.all('/mcp/*', streamable.fetch)
    app.all('/sse', sse.fetch)
    app.all('/sse/*', sse.fetch)

    app.all('*', (c) => c.notFound())
    return app
}
