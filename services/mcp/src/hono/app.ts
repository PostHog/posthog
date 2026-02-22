import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'
import type { Redis } from 'ioredis'
import { v4 as uuidv4 } from 'uuid'

import { hash } from '@/lib/utils'
import { matchAuthServerRedirect, buildRedirectUrl } from '@/lib/routing'
import type { CloudRegion } from '@/tools/types'

import { HonoMcpServer, type RequestProperties } from './mcp-server'
import {
    MCP_DOCS_URL,
    OAUTH_SCOPES_SUPPORTED,
    getAuthorizationServerUrl,
} from './constants'

import RAW_LANDING_HTML from '../static/landing.html'

const PARSED_LANDING_HTML = RAW_LANDING_HTML.replace('{{DOCS_URL}}', MCP_DOCS_URL)

type HonoEnv = {
    Variables: {
        redis: Redis
    }
}

const SESSION_TTL_MS = 30 * 60 * 1000

type SessionEntry = {
    transport: WebStandardStreamableHTTPServerTransport
    createdAt: number
}

const sessionEntries = new Map<string, SessionEntry>()

function getTransport(sessionId: string): WebStandardStreamableHTTPServerTransport | undefined {
    const entry = sessionEntries.get(sessionId)
    if (!entry) {
        return undefined
    }
    if (Date.now() - entry.createdAt > SESSION_TTL_MS) {
        sessionEntries.delete(sessionId)
        return undefined
    }
    return entry.transport
}

function storeTransport(sessionId: string, transport: WebStandardStreamableHTTPServerTransport): void {
    sessionEntries.set(sessionId, { transport, createdAt: Date.now() })
}

function removeTransport(sessionId: string): void {
    sessionEntries.delete(sessionId)
}

function evictStaleSessions(): void {
    const now = Date.now()
    for (const [sid, entry] of sessionEntries) {
        if (now - entry.createdAt > SESSION_TTL_MS) {
            sessionEntries.delete(sid)
        }
    }
}

function getRegionFromRequest(request: Request): CloudRegion | null {
    const publicUrl = getPublicUrl(request)
    if (publicUrl.hostname.toLowerCase() === 'mcp-eu.posthog.com') {
        return 'eu'
    }
    const url = new URL(request.url)
    return url.searchParams.get('region') as CloudRegion | null
}

function getPublicUrl(request: Request): URL {
    const url = new URL(request.url)
    const forwardedHost = request.headers.get('X-Forwarded-Host')
    if (forwardedHost) {
        url.host = forwardedHost
    }
    const forwardedProto = request.headers.get('X-Forwarded-Proto')
    if (forwardedProto) {
        url.protocol = forwardedProto + ':'
    }
    return url
}

export function createApp(redis: Redis): Hono<HonoEnv> {
    const app = new Hono<HonoEnv>()

    app.use('*', cors())

    app.use('*', async (c, next) => {
        c.set('redis', redis)
        await next()
    })

    app.get('/', (c) => {
        return c.html(PARSED_LANDING_HTML)
    })

    app.get('/healthz', (c) => c.json({ status: 'ok' }))
    app.get('/readyz', async (c) => {
        try {
            const result = await redis.ping()
            if (result !== 'PONG') {
                return c.json({ status: 'error', redis: 'unhealthy' }, 503)
            }
            return c.json({ status: 'ok', redis: 'healthy' })
        } catch {
            return c.json({ status: 'error', redis: 'unreachable' }, 503)
        }
    })

    app.all('/.well-known/oauth-protected-resource/*', (c) => {
        const url = new URL(c.req.url)
        const effectiveRegion = getRegionFromRequest(c.req.raw)
        const wellKnownPrefix = '/.well-known/oauth-protected-resource'
        const resourcePath = url.pathname.slice(wellKnownPrefix.length) || '/'
        const resourceUrl = getPublicUrl(c.req.raw)
        resourceUrl.pathname = resourcePath
        resourceUrl.search = ''
        const authorizationServer = getAuthorizationServerUrl(effectiveRegion)

        return c.json(
            {
                resource: resourceUrl.toString().replace(/\/$/, ''),
                authorization_servers: [authorizationServer],
                scopes_supported: OAUTH_SCOPES_SUPPORTED,
                bearer_methods_supported: ['header'],
            },
            200,
            { 'Cache-Control': 'public, max-age=3600' }
        )
    })

    const authRedirectPaths = [
        '/.well-known/oauth-authorization-server',
        '/.well-known/jwks.json',
        '/oauth/*',
        '/register',
        '/authorize',
        '/token',
    ]
    for (const path of authRedirectPaths) {
        app.all(path, (c) => {
            const url = new URL(c.req.url)
            const effectiveRegion = getRegionFromRequest(c.req.raw)
            const redirect = matchAuthServerRedirect(url.pathname)
            if (redirect) {
                const authServer = getAuthorizationServerUrl(effectiveRegion)
                const redirectTo = buildRedirectUrl(authServer, url.pathname, url.search, redirect)
                return c.redirect(redirectTo, redirect.status)
            }
            return c.notFound()
        })
    }

    async function handleMcpRequest(c: import('hono').Context<HonoEnv>): Promise<Response> {
        const url = new URL(c.req.url)
        const effectiveRegion = getRegionFromRequest(c.req.raw)

        const token = c.req.header('Authorization')?.split(' ')[1]
        if (!token) {
            const metadataUrl = getPublicUrl(c.req.raw)
            metadataUrl.pathname = `/.well-known/oauth-protected-resource${url.pathname}`
            metadataUrl.search = ''
            if (effectiveRegion) {
                metadataUrl.searchParams.set('region', effectiveRegion)
            }
            return new Response(
                `No token provided, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
                {
                    status: 401,
                    headers: { 'WWW-Authenticate': `Bearer resource_metadata="${metadataUrl.toString()}"` },
                }
            )
        }

        if (!token.startsWith('phx_') && !token.startsWith('pha_')) {
            return new Response(
                `Invalid token, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
                { status: 401 }
            )
        }

        const organizationId =
            c.req.header('x-posthog-organization-id') || url.searchParams.get('organization_id') || undefined
        const projectId =
            c.req.header('x-posthog-project-id') || url.searchParams.get('project_id') || undefined
        const featuresParam = url.searchParams.get('features')
        const features = featuresParam ? featuresParam.split(',').filter(Boolean) : undefined
        const regionParam = url.searchParams.get('region') || undefined
        const version = Number(c.req.header('x-posthog-mcp-version') || url.searchParams.get('v')) || 1
        const sessionId = url.searchParams.get('sessionId') || c.req.header('mcp-session-id') || undefined

        const props: RequestProperties = {
            apiToken: token,
            userHash: hash(token),
            sessionId,
            organizationId,
            projectId,
            features,
            region: regionParam,
            version,
        }

        const method = c.req.method

        evictStaleSessions()

        if (method === 'GET' || method === 'DELETE') {
            const existingSessionId = c.req.header('mcp-session-id')
            if (existingSessionId) {
                const transport = getTransport(existingSessionId)
                if (transport) {
                    if (method === 'DELETE') {
                        await transport.handleRequest(c.req.raw)
                        removeTransport(existingSessionId)
                        return new Response(null, { status: 200 })
                    }
                    return await transport.handleRequest(c.req.raw)
                }
            }

            if (method === 'DELETE') {
                return new Response('Session not found', { status: 404 })
            }
        }

        if (method === 'POST') {
            const existingSessionId = c.req.header('mcp-session-id')
            if (existingSessionId) {
                const transport = getTransport(existingSessionId)
                if (transport) {
                    return await transport.handleRequest(c.req.raw)
                }
            }

            const mcpServer = new HonoMcpServer(redis, props)
            await mcpServer.init()

            const transport = new WebStandardStreamableHTTPServerTransport({
                sessionIdGenerator: () => uuidv4(),
                onsessioninitialized: (sid) => {
                    storeTransport(sid, transport)
                },
            })

            transport.onclose = () => {
                if (transport.sessionId) {
                    removeTransport(transport.sessionId)
                }
            }

            await mcpServer.server.connect(transport)
            return await transport.handleRequest(c.req.raw)
        }

        return new Response('Method not allowed', { status: 405 })
    }

    app.all('/mcp', handleMcpRequest)
    app.all('/mcp/*', handleMcpRequest)

    app.all('*', (c) => c.notFound())

    return app
}
