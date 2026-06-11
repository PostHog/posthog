import { Hono } from 'hono'

import { httpMetrics, securityHeaders } from './middleware'
import { registerPublicRoutes } from './public-routes'
import { StreamableMcpHandler } from './streamable-handler'
import type { HonoCtx, RedisWithPing } from './types'

export type Lifecycle = { shuttingDown: boolean }

export type App = {
    app: Hono
    lifecycle: Lifecycle
    warmup: () => Promise<void>
}

const sseRedirect = (c: HonoCtx): Response => {
    const target = new URL(c.req.url)
    target.pathname = '/mcp' + target.pathname.slice('/sse'.length)
    target.searchParams.set('_deprecated', 'sse')
    return c.redirect(target.toString(), 308) as unknown as Response
}

export function createApp(redis: RedisWithPing): App {
    const app = new Hono()
    const lifecycle: Lifecycle = { shuttingDown: false }

    app.use('*', securityHeaders)
    app.use('*', httpMetrics)

    registerPublicRoutes(app, redis, lifecycle)

    app.all('/sse', sseRedirect)
    app.all('/sse/*', sseRedirect)

    const streamable = new StreamableMcpHandler(redis, lifecycle)

    app.all('/mcp', streamable.fetch)
    app.all('/mcp/*', streamable.fetch)

    app.all('*', (c) => c.notFound())

    return {
        app,
        lifecycle,
        warmup: () => streamable.warmup(),
    }
}
