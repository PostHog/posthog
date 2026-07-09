// Named Hono middleware exports for the agent-proxy.
//
// securityHeaders — X-Content-Type-Options, X-Frame-Options on every response.
// corsHeaders     — Access-Control-Allow-Origin / Vary on matching origin responses.
// httpMetrics     — prom-client counter + histogram + inflight gauge per request.
// requestLog      — wide-event RequestLogger summary line at INFO level.

import type { MiddlewareHandler } from 'hono'

import type { Config } from '../lib/config.js'
import { CORS_ALLOW_HEADERS, CORS_ALLOW_METHODS, CORS_MAX_AGE } from '../lib/constants.js'
import { RequestLogger, logger, redactHeaders } from '../lib/logging.js'
import { httpRequestDurationSeconds, httpRequestsTotal, inflightRequests, routeLabel } from './metrics.js'
import { PROBE_PATHS } from './public-routes.js'
import type { HonoVariables } from './types.js'

export const securityHeaders: MiddlewareHandler = async (c, next) => {
    await next()
    c.header('X-Content-Type-Options', 'nosniff')
    c.header('X-Frame-Options', 'DENY')
}

export function corsHeaders(config: Config): MiddlewareHandler {
    return async (c, next) => {
        const origin = c.req.header('Origin')
        await next()
        if (!origin) {
            return
        }
        const allowed = config.corsOrigins.has('*') || config.corsOrigins.has(origin)
        if (allowed) {
            c.header('Access-Control-Allow-Origin', origin)
            c.header('Vary', 'Origin')
        }
    }
}

// Skip /_metrics itself to avoid self-scrape noise inflating the histograms.
// Uses prom-client's startTimer so the observation fires even if next() throws.
export const httpMetrics: MiddlewareHandler = async (c, next) => {
    const pathname = new URL(c.req.url).pathname
    if (pathname === '/_metrics') {
        return next()
    }

    const route = routeLabel(pathname)
    inflightRequests.labels({ route }).inc()
    const endTimer = httpRequestDurationSeconds.startTimer({ method: c.req.method, route })

    try {
        await next()
    } finally {
        const status = String(c.res.status)
        inflightRequests.labels({ route }).dec()
        httpRequestsTotal.labels({ method: c.req.method, route, status }).inc()
        endTimer({ status })
    }
}

// Emit one structured summary line per non-probe request at INFO level.
// Route handlers may call c.get('requestLogger').extend({ ... }) to merge
// domain-specific fields (run ID, accepted count, etc.) into the summary.
export const requestLog: MiddlewareHandler<{ Variables: HonoVariables }> = async (c, next) => {
    const pathname = new URL(c.req.url).pathname
    if (PROBE_PATHS.has(pathname)) {
        return next()
    }

    const log = new RequestLogger()
    c.set('requestLogger', log)

    // Capture a curated subset of request headers (redact sensitive values).
    const rawHeaders: Record<string, string> = {}
    c.req.raw.headers.forEach((value, key) => {
        rawHeaders[key] = value
    })
    log.extend({
        method: c.req.method,
        path: pathname,
        headers: redactHeaders(rawHeaders),
    })

    try {
        await next()
    } finally {
        logger.info('http.request', log.finish(c.res.status))
    }
}

// CORS preflight handler — registered on app.options('*') in app.ts.
// Returns 204 with CORS headers when origin is in the allowlist.
export function corsPreflightHandler(config: Config): MiddlewareHandler {
    return async (c) => {
        const origin = c.req.header('Origin')
        if (origin && (config.corsOrigins.has('*') || config.corsOrigins.has(origin))) {
            c.header('Access-Control-Allow-Origin', origin)
            c.header('Vary', 'Origin')
            c.header('Access-Control-Allow-Methods', CORS_ALLOW_METHODS)
            c.header('Access-Control-Allow-Headers', CORS_ALLOW_HEADERS)
            c.header('Access-Control-Max-Age', CORS_MAX_AGE)
        }
        return c.body(null, 204)
    }
}
