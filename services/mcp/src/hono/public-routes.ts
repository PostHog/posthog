import { serveStatic } from '@hono/node-server/serve-static'
import type { Hono } from 'hono'

import { buildRedirectUrl, getPublicUrl, matchAuthServerRedirect } from '@/lib/routing'

import {
    AUTH_REDIRECT_PATHS,
    getAuthorizationServerUrl,
    MCP_DOCS_URL,
    OAUTH_SCOPES_SUPPORTED,
} from './constants'
import type { HonoCtx, HonoEnv, RedisWithPing } from './types'

import RAW_LANDING_HTML from '../static/landing.html'

const PARSED_LANDING_HTML = RAW_LANDING_HTML.replace('{{DOCS_URL}}', MCP_DOCS_URL)
const WELL_KNOWN_PREFIX = '/.well-known/oauth-protected-resource'
const OPENAI_CHALLENGE_TOKEN = 'pRLV9JYbPOF5Dy039v3Rn3-qrMuKqZ2_4SsX9GoL9aU'

const healthHandler = (c: HonoCtx): Response =>
    c.json({ status: 'ok' }, 200, { 'Cache-Control': 'no-store' })

function readyzHandler(redis: RedisWithPing) {
    return async (c: HonoCtx): Promise<Response> => {
        try {
            if (redis.ping) {
                if ((await redis.ping()) !== 'PONG') {
                    return c.json({ status: 'error', redis: 'unhealthy' }, 503)
                }
            } else {
                // Fallback for RedisLike implementations without `ping` — a 10s
                // SET round-trip is enough to confirm reachability.
                await redis.set('__readyz', 'ok', 'EX', 10)
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
export function registerPublicRoutes(app: Hono<HonoEnv>, redis: RedisWithPing): void {
    // MCP UI app static assets. The CF runtime serves these via the Workers
    // Static Assets binding (`wrangler.jsonc`'s `assets.directory: ./public/`);
    // here we serve them from disk so the same `${MCP_APPS_BASE_URL}/ui-apps/...`
    // URL pattern works on both runtimes.
    app.use('/ui-apps/*', serveStatic({ root: './public' }))

    app.get('/', (c) => c.html(PARSED_LANDING_HTML))
    app.get('/.well-known/openai-apps-challenge', (c) => c.text(OPENAI_CHALLENGE_TOKEN))
    app.get('/health', healthHandler)
    app.get('/healthz', healthHandler)
    app.get('/readyz', readyzHandler(redis))

    app.all(WELL_KNOWN_PREFIX, wellKnownHandler)
    app.all(`${WELL_KNOWN_PREFIX}/*`, wellKnownHandler)

    for (const path of AUTH_REDIRECT_PATHS) {
        app.all(path, authRedirectHandler)
    }
}
