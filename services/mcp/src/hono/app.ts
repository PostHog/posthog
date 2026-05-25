import { Hono } from 'hono'

import { httpMetrics, securityHeaders } from './middleware'
import { registerPublicRoutes } from './public-routes'
import { type BusAwaitMetrics, createPromBusMetrics, type SessionResponseBus } from './session-bus'
import { StreamableMcpHandler } from './streamable-handler'
import type { HonoCtx, RedisWithPing } from './types'

export type Lifecycle = { shuttingDown: boolean }

export type App = {
    app: Hono
    lifecycle: Lifecycle
    warmup: () => Promise<void>
}

export interface CreateAppOptions {
    /**
     * Override the cross-pod session bus used by the dispatcher for
     * elicitation correlation. Tests inject `InMemorySessionResponseBus`;
     * production uses the Redis-polling default constructed by the
     * dispatcher itself.
     */
    sessionBus?: SessionResponseBus
    /**
     * Override the per-await metrics adapter. Defaults to a Prometheus
     * adapter that pushes into `mcp_session_bus_*`. Tests typically leave
     * this undefined or pass a spy.
     */
    busMetrics?: BusAwaitMetrics
}

const sseRedirect = (c: HonoCtx): Response => {
    const target = new URL(c.req.url)
    target.pathname = '/mcp' + target.pathname.slice('/sse'.length)
    target.searchParams.set('_deprecated', 'sse')
    return c.redirect(target.toString(), 308) as unknown as Response
}

export function createApp(redis: RedisWithPing, options: CreateAppOptions = {}): App {
    const app = new Hono()
    const lifecycle: Lifecycle = { shuttingDown: false }

    app.use('*', securityHeaders)
    app.use('*', httpMetrics)

    registerPublicRoutes(app, redis, lifecycle)

    app.all('/sse', sseRedirect)
    app.all('/sse/*', sseRedirect)

    const dispatcherOptions: { sessionBus?: SessionResponseBus; busMetrics?: BusAwaitMetrics } = {
        busMetrics: options.busMetrics ?? createPromBusMetrics(),
    }
    if (options.sessionBus !== undefined) {
        dispatcherOptions.sessionBus = options.sessionBus
    }
    const streamable = new StreamableMcpHandler(redis, lifecycle, dispatcherOptions)

    app.all('/mcp', streamable.fetch)
    app.all('/mcp/*', streamable.fetch)

    app.all('*', (c) => c.notFound())

    return {
        app,
        lifecycle,
        warmup: () => streamable.warmup(),
    }
}
