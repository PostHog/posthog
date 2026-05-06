import { Hono } from 'hono'

import { type Lifecycle, newLifecycle } from './lifecycle'
import { attachRedis, corsMiddleware, securityHeaders } from './middleware'
import { registerPublicRoutes } from './public-routes'
import { SessionStore } from './session-store'
import { StreamableMcpHandler } from './streamable-handler'
import type { HonoCtx, HonoEnv, RedisWithPing } from './types'

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
export type App = {
    app: Hono<HonoEnv>
    store: SessionStore
    lifecycle: Lifecycle
}

export function createApp(redis: RedisWithPing): App {
    const app = new Hono<HonoEnv>()
    const store = new SessionStore()
    const lifecycle = newLifecycle()

    app.use('*', securityHeaders)
    app.use('*', corsMiddleware)
    app.use('*', attachRedis(redis))

    registerPublicRoutes(app, redis, lifecycle)

    // Legacy `/sse*` clients are redirected to `/mcp*`. Permanent so caches and
    // OAuth metadata followers update; `_deprecated=sse` is propagated so the
    // followup `/mcp` request shows up in analytics with `viaSseRedirect`.
    const sseRedirect = (c: HonoCtx): Response => {
        const target = new URL(c.req.url)
        target.pathname = '/mcp' + target.pathname.slice('/sse'.length)
        target.searchParams.set('_deprecated', 'sse')
        return c.redirect(target.toString(), 308) as unknown as Response
    }
    app.all('/sse', sseRedirect)
    app.all('/sse/*', sseRedirect)

    const streamable = new StreamableMcpHandler(redis, store, lifecycle)
    app.all('/mcp', streamable.fetch)
    app.all('/mcp/*', streamable.fetch)

    app.all('*', (c) => c.notFound())
    return { app, store, lifecycle }
}
