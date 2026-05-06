import { serveStatic } from '@hono/node-server/serve-static'
import type { Hono } from 'hono'

import { buildRedirectUrl, getPublicUrl, matchAuthServerRedirect } from '@/lib/routing'

import {
    AUTH_REDIRECT_PATHS,
    getAuthorizationServerUrl,
    MCP_DOCS_URL,
    OAUTH_SCOPES_SUPPORTED,
} from './constants'
import type { Lifecycle } from './lifecycle'
import { register } from './metrics'
import type { HonoCtx, HonoEnv, RedisWithPing } from './types'

const WELL_KNOWN_PREFIX = '/.well-known/oauth-protected-resource'
const OPENAI_CHALLENGE_TOKEN = 'pRLV9JYbPOF5Dy039v3Rn3-qrMuKqZ2_4SsX9GoL9aU'
// Cap on Redis ping for readiness checks. Long enough to ride out a normal hop,
// short enough that a tarpit doesn't block kubelet probes.
const READYZ_REDIS_TIMEOUT_MS = 500

const healthHandler = (c: HonoCtx): Response =>
    c.json({ status: 'ok' }, 200, { 'Cache-Control': 'no-store' })

function readyzHandler(redis: RedisWithPing, lifecycle: Lifecycle) {
    return async (c: HonoCtx): Promise<Response> => {
        // Flip readiness off as soon as SIGTERM lands so kube-proxy evicts us
        // before we start refusing connections.
        if (lifecycle.shuttingDown) {
            return c.json({ status: 'shutting_down' }, 503)
        }
        try {
            const probe = redis.ping
                ? redis.ping().then((v) => v === 'PONG')
                : redis.set('mcp:health:__readyz', 'ok', 'EX', 10).then((v) => v !== null)
            const ok = await Promise.race([
                probe,
                new Promise<false>((resolve) => setTimeout(() => resolve(false), READYZ_REDIS_TIMEOUT_MS)),
            ])
            if (!ok) {
                return c.json({ status: 'error', redis: 'unhealthy' }, 503)
            }
            return c.json({ status: 'ok', redis: 'healthy' })
        } catch {
            return c.json({ status: 'error', redis: 'unreachable' }, 503)
        }
    }
}

// RFC 9728: insert `/.well-known/oauth-protected-resource` between host and
// resource path. The resource URL the metadata advertises has to match what
// the client connected on, so we derive it from the request rather than
// hard-coding the host.
const wellKnownHandler = (c: HonoCtx): Response => {
    const url = new URL(c.req.url)
    const resourcePath = url.pathname.slice(WELL_KNOWN_PREFIX.length) || '/'
    const resourceUrl = getPublicUrl(c.req.raw)
    resourceUrl.pathname = resourcePath
    resourceUrl.search = ''

    return c.json(
        {
            resource: resourceUrl.toString().replace(/\/$/, ''),
            authorization_servers: [getAuthorizationServerUrl()],
            scopes_supported: OAUTH_SCOPES_SUPPORTED,
            bearer_methods_supported: ['header'],
        },
        200,
        { 'Cache-Control': 'public, max-age=3600' }
    )
}

const authRedirectHandler = (c: HonoCtx): Response => {
    const url = new URL(c.req.url)
    const redirect = matchAuthServerRedirect(url.pathname)
    if (!redirect) {
        return c.notFound() as unknown as Response
    }
    const redirectTo = buildRedirectUrl(getAuthorizationServerUrl(), url.pathname, url.search, redirect)
    return c.redirect(redirectTo, redirect.status) as unknown as Response
}

/**
 * Routes that don't require authentication: landing, healthchecks, OAuth
 * resource metadata, MCP UI app static assets, and auth-server fallback redirects.
 */
export function registerPublicRoutes(app: Hono<HonoEnv>, redis: RedisWithPing, lifecycle: Lifecycle): void {
    // MCP UI app static assets. The CF runtime serves these via the Workers
    // Static Assets binding (`wrangler.jsonc`'s `assets.directory: ./public/`);
    // here we serve them from disk so the same `${MCP_APPS_BASE_URL}/ui-apps/...`
    // URL pattern works on both runtimes.
    app.use('/ui-apps/*', serveStatic({ root: './public' }))

    app.get('/', (c) => c.redirect(MCP_DOCS_URL, 302) as unknown as Response)
    app.get('/.well-known/openai-apps-challenge', (c) => c.text(OPENAI_CHALLENGE_TOKEN))
    app.get('/health', healthHandler)
    app.get('/healthz', healthHandler)
    app.get('/readyz', readyzHandler(redis, lifecycle))
    app.get('/metrics', async (c) => {
        c.header('Content-Type', register.contentType)
        return c.body(await register.metrics())
    })

    app.all(WELL_KNOWN_PREFIX, wellKnownHandler)
    app.all(`${WELL_KNOWN_PREFIX}/*`, wellKnownHandler)

    for (const path of AUTH_REDIRECT_PATHS) {
        app.all(path, authRedirectHandler)
    }
}
