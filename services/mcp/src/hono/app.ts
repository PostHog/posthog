import { Hono } from 'hono'

import { httpMetrics, securityHeaders } from './middleware'
import { registerPublicRoutes } from './public-routes'
import {
    type BusAwaitMetrics,
    createPromBusMetrics,
    RedisPollingSessionResponseBus,
    type SessionResponseBus,
} from './session-bus'
import { StreamableMcpHandler } from './streamable-handler'
import type { HonoCtx, RedisWithPing } from './types'

export type Lifecycle = { shuttingDown: boolean }

export type App = {
    app: Hono
    lifecycle: Lifecycle
    sessionBus: SessionResponseBus
}

export interface CreateAppOptions {
    /**
     * Override the session bus. Tests inject `InMemorySessionResponseBus`;
     * production wires the default `RedisPollingSessionResponseBus` against
     * the shared Redis client.
     */
    sessionBus?: SessionResponseBus
    /**
     * Override the per-await metrics adapter. Defaults to a Prometheus
     * adapter that pushes into `mcp_session_bus_*`. Tests typically leave
     * this undefined or pass a spy.
     */
    busMetrics?: BusAwaitMetrics
}

export function createApp(redis: RedisWithPing, options: CreateAppOptions = {}): App {
    const app = new Hono()
    const lifecycle: Lifecycle = { shuttingDown: false }

    const sessionBus = options.sessionBus ?? new RedisPollingSessionResponseBus(redis)
    const busMetrics = options.busMetrics ?? createPromBusMetrics()

    app.use('*', securityHeaders)
    app.use('*', httpMetrics)

    registerPublicRoutes(app, redis, lifecycle)

    const sseRedirect = (c: HonoCtx): Response => {
        const target = new URL(c.req.url)
        target.pathname = '/mcp' + target.pathname.slice('/sse'.length)
        target.searchParams.set('_deprecated', 'sse')
        return c.redirect(target.toString(), 308) as unknown as Response
    }
    app.all('/sse', sseRedirect)
    app.all('/sse/*', sseRedirect)

    const streamable = new StreamableMcpHandler(redis, lifecycle, sessionBus, busMetrics)
    app.all('/mcp', streamable.fetch)
    app.all('/mcp/*', streamable.fetch)

    app.all('*', (c) => c.notFound())
    return { app, lifecycle, sessionBus }
}
