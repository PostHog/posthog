import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js'
import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'
import type { Redis } from 'ioredis'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { v4 as uuidv4 } from 'uuid'

import { ErrorCode } from '@/lib/errors'
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

type StreamableSessionEntry = {
    transport: WebStandardStreamableHTTPServerTransport
    createdAt: number
}

type SSESessionEntry = {
    transport: SSEServerTransport
    server: HonoMcpServer
    createdAt: number
}

const streamableSessions = new Map<string, StreamableSessionEntry>()
const sseSessions = new Map<string, SSESessionEntry>()

function getStreamableTransport(sessionId: string): WebStandardStreamableHTTPServerTransport | undefined {
    const entry = streamableSessions.get(sessionId)
    if (!entry) {
        return undefined
    }
    if (Date.now() - entry.createdAt > SESSION_TTL_MS) {
        streamableSessions.delete(sessionId)
        return undefined
    }
    return entry.transport
}

function evictStaleSessions(): void {
    const now = Date.now()
    for (const [sid, entry] of streamableSessions) {
        if (now - entry.createdAt > SESSION_TTL_MS) {
            streamableSessions.delete(sid)
        }
    }
    for (const [sid, entry] of sseSessions) {
        if (now - entry.createdAt > SESSION_TTL_MS) {
            sseSessions.delete(sid)
        }
    }
}

function getRegionFromHostname(hostname: string): CloudRegion | undefined {
    const h = hostname.toLowerCase()
    if (h === 'mcp.eu.posthog.com' || h === 'mcp-eu.posthog.com') {
        return 'eu'
    }
    if (h === 'mcp.us.posthog.com') {
        return 'us'
    }
    return undefined
}

function getRegionFromRequest(request: Request): CloudRegion | null {
    const publicUrl = getPublicUrl(request)
    const hostnameRegion = getRegionFromHostname(publicUrl.hostname)
    if (hostnameRegion) {
        return hostnameRegion
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

function extractRequestProps(c: import('hono').Context<HonoEnv>): {
    token: string | undefined
    url: URL
    effectiveRegion: CloudRegion | null
} {
    const url = new URL(c.req.url)
    const effectiveRegion = getRegionFromRequest(c.req.raw)
    const token = c.req.header('Authorization')?.split(' ')[1]
    return { token, url, effectiveRegion }
}

function buildAuthErrorResponse(token: string | undefined, url: URL, effectiveRegion: CloudRegion | null, request: Request): Response | null {
    if (!token) {
        const metadataUrl = getPublicUrl(request)
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

    return null
}

function buildRequestProperties(c: import('hono').Context<HonoEnv>, token: string, url: URL): RequestProperties {
    const organizationId =
        c.req.header('x-posthog-organization-id') || url.searchParams.get('organization_id') || undefined
    const projectId =
        c.req.header('x-posthog-project-id') || url.searchParams.get('project_id') || undefined
    const featuresParam = url.searchParams.get('features')
    const features = featuresParam ? featuresParam.split(',').filter(Boolean) : undefined
    const regionParam = url.searchParams.get('region') || undefined
    const version = Number(c.req.header('x-posthog-mcp-version') || url.searchParams.get('v')) || 1
    const sessionId = url.searchParams.get('sessionId') || c.req.header('mcp-session-id') || undefined

    return {
        apiToken: token,
        userHash: hash(token),
        sessionId,
        organizationId,
        projectId,
        features,
        region: regionParam,
        version,
    }
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

    // Auth server redirects — checked BEFORE well-known endpoints (matches CF impl order)
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

    // OAuth Protected Resource Metadata (RFC 9728)
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

    // Streamable HTTP MCP endpoint (/mcp)
    async function handleMcpRequest(c: import('hono').Context<HonoEnv>): Promise<Response> {
        const { token, url, effectiveRegion } = extractRequestProps(c)
        const authError = buildAuthErrorResponse(token, url, effectiveRegion, c.req.raw)
        if (authError) {
            return authError
        }

        const props = buildRequestProperties(c, token!, url)
        const method = c.req.method

        evictStaleSessions()

        if (method === 'GET' || method === 'DELETE') {
            const existingSessionId = c.req.header('mcp-session-id')
            if (existingSessionId) {
                const transport = getStreamableTransport(existingSessionId)
                if (transport) {
                    if (method === 'DELETE') {
                        await transport.handleRequest(c.req.raw)
                        streamableSessions.delete(existingSessionId)
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
                const transport = getStreamableTransport(existingSessionId)
                if (transport) {
                    return await transport.handleRequest(c.req.raw)
                }
            }

            const mcpServer = new HonoMcpServer(redis, props)
            await mcpServer.init()

            const transport = new WebStandardStreamableHTTPServerTransport({
                sessionIdGenerator: () => uuidv4(),
                onsessioninitialized: (sid) => {
                    streamableSessions.set(sid, { transport, createdAt: Date.now() })
                },
            })

            transport.onclose = () => {
                if (transport.sessionId) {
                    streamableSessions.delete(transport.sessionId)
                }
            }

            await mcpServer.server.connect(transport)
            const response = await transport.handleRequest(c.req.raw)
            return errorHandler(response)
        }

        return new Response('Method not allowed', { status: 405 })
    }

    // SSE MCP endpoint (/sse) — matches CF's MCP.serveSSE('/sse')
    async function handleSseRequest(c: import('hono').Context<HonoEnv>): Promise<Response> {
        const { token, url, effectiveRegion } = extractRequestProps(c)
        const authError = buildAuthErrorResponse(token, url, effectiveRegion, c.req.raw)
        if (authError) {
            return authError
        }

        const props = buildRequestProperties(c, token!, url)
        const method = c.req.method

        evictStaleSessions()

        if (method === 'GET') {
            const sessionId = uuidv4()

            const mcpServer = new HonoMcpServer(redis, props)
            await mcpServer.init()

            const stream = new ReadableStream({
                start(controller) {
                    const encoder = new TextEncoder()
                    const pseudoRes = {
                        writeHead: () => pseudoRes,
                        write: (chunk: string) => {
                            controller.enqueue(encoder.encode(chunk))
                            return true
                        },
                        on: () => pseudoRes,
                        end: () => {
                            controller.close()
                            sseSessions.delete(sessionId)
                        },
                    } as unknown as ServerResponse

                    const transport = new SSEServerTransport('/sse', pseudoRes)

                    sseSessions.set(sessionId, { transport, server: mcpServer, createdAt: Date.now() })

                    mcpServer.server.connect(transport).then(() => transport.start())
                },
            })

            return new Response(stream, {
                headers: {
                    'Content-Type': 'text/event-stream',
                    'Cache-Control': 'no-cache',
                    Connection: 'keep-alive',
                },
            })
        }

        if (method === 'POST') {
            const sessionId = url.searchParams.get('sessionId')
            if (!sessionId) {
                return new Response('Missing sessionId', { status: 400 })
            }
            const session = sseSessions.get(sessionId)
            if (!session) {
                return new Response('Session not found', { status: 404 })
            }
            const body = await c.req.json()
            const pseudoReq = {
                method: 'POST',
                headers: Object.fromEntries(c.req.raw.headers.entries()),
                url: c.req.url,
            } as unknown as IncomingMessage
            const pseudoRes = {
                writeHead: () => pseudoRes,
                end: () => undefined,
            } as unknown as ServerResponse
            await session.transport.handlePostMessage(pseudoReq, pseudoRes, body)
            return new Response('Accepted', { status: 202 })
        }

        return new Response('Method not allowed', { status: 405 })
    }

    app.all('/mcp', handleMcpRequest)
    app.all('/mcp/*', handleMcpRequest)
    app.all('/sse', handleSseRequest)
    app.all('/sse/*', handleSseRequest)

    app.all('*', (c) => c.notFound())

    return app
}

async function errorHandler(response: Response): Promise<Response> {
    if (!response.ok) {
        const body = await response.clone().text()
        if (body.includes(ErrorCode.INACTIVE_OAUTH_TOKEN)) {
            return new Response('OAuth token is inactive', { status: 401 })
        }
    }
    return response
}
