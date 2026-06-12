import { Hono } from 'hono'

import { loadSigningKeyFromEnv, NonceLedger, SignedStateCodec } from '@/lib/signed-state'
import { setConfirmedActionRuntime } from '@/tools/confirmed-action-registry'

import { confirmedActionRuntimeInstalled } from './metrics'
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

    // Install/refresh the process-level typed-confirm runtime singleton.
    // Generated -prepare/-execute handlers call getConfirmedActionRuntime()
    // at request time and throw if it's missing, so do this before any
    // tool dispatch. createApp may be invoked multiple times (e.g. tests
    // creating fresh app instances) — each call overwrites the singleton;
    // that's intentional, the latest installation wins.
    //
    // No MCP_SIGNED_STATE_KEY → skip install. Tools without confirmed_action
    // keep working; -prepare/-execute calls throw at request time with a
    // message pointing at the missing env var. Log loudly so ops sees the
    // misconfig before a real confirmed_action tool lands.
    try {
        setConfirmedActionRuntime({
            codec: new SignedStateCodec(loadSigningKeyFromEnv()),
            ledger: new NonceLedger(redis),
        })
        confirmedActionRuntimeInstalled.set(1)
    } catch (err) {
        setConfirmedActionRuntime(undefined)
        confirmedActionRuntimeInstalled.set(0)
        console.error(
            `[mcp] CRITICAL: confirmed-action paradigm disabled — ${(err as Error).message}. ` +
                `Any -prepare/-execute tool call will fail until this is fixed.`
        )
    }

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
