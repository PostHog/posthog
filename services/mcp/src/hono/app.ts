import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'
import type { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js'
import { Hono } from 'hono'
import { cors } from 'hono/cors'
import { v4 as uuidv4 } from 'uuid'

import { getPostHogClient } from '@/lib/analytics'
import {
    buildInsufficientScopeChallenge,
    ErrorCode,
    findPostHogPermissionError,
    formatPermissionErrorMessage,
} from '@/lib/errors'
import { extractClientInfoFromBody } from '@/lib/mcp-client-info'
import { buildRedirectUrl, matchAuthServerRedirect } from '@/lib/routing'
import { hash, parseMcpMode, sanitizeHeaderValue } from '@/lib/utils'
import type { CloudRegion } from '@/tools/types'

import type { RedisLike } from './cache/RedisCache'
import {
    getAuthorizationServerUrl,
    MCP_DOCS_URL,
    OAUTH_SCOPES_SUPPORTED,
} from './constants'
import { HonoMcpServer, type RequestProperties } from './mcp-server'
import { createSSEResponseAdapter, handleSSEPostMessage } from './sse-adapter'

import RAW_LANDING_HTML from '../static/landing.html'

const PARSED_LANDING_HTML = RAW_LANDING_HTML.replace('{{DOCS_URL}}', MCP_DOCS_URL)
const SESSION_TTL_MS = 30 * 60 * 1000
const MAX_SESSIONS_PER_INSTANCE = 10_000

type HonoEnv = { Variables: { redis: RedisLike } }
type SessionEntry<T> = { transport: T; createdAt: number; tokenHash: string }

// Helper to get the public-facing URL, respecting reverse proxy headers
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

// Detect region from hostname for EU subdomain routing.
// See: https://github.com/anthropics/claude-code/issues/2267
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

// Detect region from hostname (mcp-eu.posthog.com) or query param (?region=eu)
function getRegionFromRequest(request: Request): CloudRegion | null {
    const publicUrl = getPublicUrl(request)
    const hostnameRegion = getRegionFromHostname(publicUrl.hostname)
    if (hostnameRegion) {
        return hostnameRegion
    }
    const url = new URL(request.url)
    return url.searchParams.get('region') as CloudRegion | null
}

function buildAuthErrorResponse(
    token: string | undefined,
    url: URL,
    effectiveRegion: CloudRegion | null,
    request: Request
): Response | null {
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

function buildRequestProperties(
    c: import('hono').Context<HonoEnv>,
    token: string,
    url: URL,
    transport: 'streamable-http' | 'sse',
    clientInfo: { clientName?: string; clientVersion?: string; protocolVersion?: string }
): RequestProperties {
    const organizationId =
        c.req.header('x-posthog-organization-id') || url.searchParams.get('organization_id') || undefined
    const projectId =
        c.req.header('x-posthog-project-id') || url.searchParams.get('project_id') || undefined
    const featuresParam = url.searchParams.get('features')
    const features = featuresParam ? featuresParam.split(',').filter(Boolean) : undefined
    const toolsParam = url.searchParams.get('tools')
    const tools = toolsParam ? toolsParam.split(',').filter(Boolean) : undefined
    const regionParam = url.searchParams.get('region') || undefined
    const version = Number(c.req.header('x-posthog-mcp-version') || url.searchParams.get('v')) || 1
    const sessionId = url.searchParams.get('sessionId') || undefined
    const readOnlyRaw = c.req.header('x-posthog-readonly') || url.searchParams.get('readonly')
    const readOnly = readOnlyRaw === 'true' || readOnlyRaw === '1' || undefined
    const rawUserAgent = c.req.header('User-Agent') || undefined
    const clientUserAgent = sanitizeHeaderValue(rawUserAgent)
    const mcpConsumer = sanitizeHeaderValue(c.req.header('x-posthog-mcp-consumer') || undefined)
    const mode = parseMcpMode(c.req.header('x-posthog-mcp-mode') || url.searchParams.get('mode'))

    return {
        apiToken: token,
        userHash: hash(token),
        sessionId,
        organizationId,
        projectId,
        features,
        tools,
        region: regionParam,
        version,
        readOnly,
        clientUserAgent,
        mcpConsumer,
        mcpClientName: clientInfo.clientName,
        mcpClientVersion: clientInfo.clientVersion,
        mcpProtocolVersion: clientInfo.protocolVersion,
        mode,
        transport,
        requestStartTime: Date.now(),
    }
}

async function errorHandler(response: Response): Promise<Response> {
    if (!response.ok) {
        const body = await response.clone().text()
        if (body.includes(ErrorCode.INACTIVE_OAUTH_TOKEN)) {
            return new Response('OAuth token is inactive', { status: 401 })
        }
        if (body.includes(ErrorCode.INVALID_API_KEY)) {
            return new Response('Invalid API key', { status: 401 })
        }
    }
    return response
}

function handleCatchError(error: unknown, tokenHash?: string, transport?: string): Response {
    const permissionError = findPostHogPermissionError(error)
    if (permissionError) {
        return new Response(formatPermissionErrorMessage(permissionError), {
            status: 403,
            headers: {
                'Content-Type': 'text/plain; charset=utf-8',
                'WWW-Authenticate': buildInsufficientScopeChallenge(permissionError),
            },
        })
    }

    if (error instanceof Error) {
        if (error.message.includes(ErrorCode.INACTIVE_OAUTH_TOKEN)) {
            return new Response('OAuth token is inactive', { status: 401 })
        }
        if (error.message.includes(ErrorCode.INVALID_API_KEY)) {
            return new Response('Invalid API key', { status: 401 })
        }
    }

    try {
        const client = getPostHogClient()
        if (error instanceof Error) {
            client.captureException(error, tokenHash, {
                team: 'posthog_ai',
                source: 'mcp_hono_request',
                mcp_transport: transport,
            })
        }
    } catch {
        // Never let observability break the request.
    }

    return new Response('Internal server error', { status: 500 })
}

export function createApp(redis: RedisLike & { ping?(): Promise<string> }): Hono<HonoEnv> {
    const app = new Hono<HonoEnv>()

    const streamableSessions = new Map<string, SessionEntry<WebStandardStreamableHTTPServerTransport>>()
    const sseSessions = new Map<string, SessionEntry<SSEServerTransport> & { server: HonoMcpServer }>()

    function getStreamableTransport(
        sessionId: string,
        tokenHash: string
    ): WebStandardStreamableHTTPServerTransport | undefined {
        const entry = streamableSessions.get(sessionId)
        if (!entry) {
            return undefined
        }
        if (Date.now() - entry.createdAt > SESSION_TTL_MS) {
            streamableSessions.delete(sessionId)
            return undefined
        }
        if (entry.tokenHash !== tokenHash) {
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

    function totalSessionCount(): number {
        return streamableSessions.size + sseSessions.size
    }

    // Security headers middleware
    app.use('*', async (c, next) => {
        await next()
        c.header('X-Content-Type-Options', 'nosniff')
        c.header('X-Frame-Options', 'DENY')
    })

    // CORS middleware
    app.use(
        '*',
        cors({
            origin: (origin) => origin,
            allowMethods: ['GET', 'POST', 'DELETE', 'OPTIONS'],
            allowHeaders: [
                'Authorization',
                'Content-Type',
                'mcp-session-id',
                'x-posthog-organization-id',
                'x-posthog-project-id',
                'x-posthog-mcp-version',
                'x-posthog-readonly',
                'x-posthog-mcp-consumer',
                'x-posthog-mcp-mode',
            ],
            exposeHeaders: ['mcp-session-id'],
            maxAge: 86400,
        })
    )

    // Redis middleware
    app.use('*', async (c, next) => {
        c.set('redis', redis)
        await next()
    })

    // Landing page
    app.get('/', (c) => c.html(PARSED_LANDING_HTML))

    // OpenAI ChatGPT App Directory domain verification
    app.get('/.well-known/openai-apps-challenge', (c) => {
        return c.text('pRLV9JYbPOF5Dy039v3Rn3-qrMuKqZ2_4SsX9GoL9aU')
    })

    // Health endpoints
    app.get('/health', (c) => c.json({ status: 'ok' }, 200, { 'Cache-Control': 'no-store' }))
    app.get('/healthz', (c) => c.json({ status: 'ok' }))

    // Readiness probe
    app.get('/readyz', async (c) => {
        try {
            if (redis.ping) {
                const result = await redis.ping()
                if (result !== 'PONG') {
                    return c.json({ status: 'error', redis: 'unhealthy' }, 503)
                }
            } else {
                await redis.set('__readyz', 'ok', 'EX', 10)
            }
            return c.json({ status: 'ok', redis: 'healthy' })
        } catch {
            return c.json({ status: 'error', redis: 'unreachable' }, 503)
        }
    })

    // OAuth Protected Resource Metadata (RFC 9728)
    const wellKnownHandler = (c: import('hono').Context<HonoEnv>): Response => {
        const url = new URL(c.req.url)
        const wellKnownPrefix = '/.well-known/oauth-protected-resource'
        const resourcePath = url.pathname.slice(wellKnownPrefix.length) || '/'
        const resourceUrl = getPublicUrl(c.req.raw)
        resourceUrl.pathname = resourcePath
        resourceUrl.search = ''
        const authorizationServer = getAuthorizationServerUrl()

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
    }
    app.all('/.well-known/oauth-protected-resource', wellKnownHandler)
    app.all('/.well-known/oauth-protected-resource/*', wellKnownHandler)

    // Authorization server redirects
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
            const redirect = matchAuthServerRedirect(url.pathname)
            if (redirect) {
                const authServer = getAuthorizationServerUrl()
                const redirectTo = buildRedirectUrl(authServer, url.pathname, url.search, redirect)
                return c.redirect(redirectTo, redirect.status)
            }
            return c.notFound()
        })
    }

    // MCP Streamable HTTP endpoint
    async function handleMcpRequest(c: import('hono').Context<HonoEnv>): Promise<Response> {
        const url = new URL(c.req.url)
        const effectiveRegion = getRegionFromRequest(c.req.raw)
        const token = c.req.header('Authorization')?.split(' ')[1]

        const authError = buildAuthErrorResponse(token, url, effectiveRegion, c.req.raw)
        if (authError) {
            return authError
        }

        const clientInfo = await extractClientInfoFromBody(c.req.raw)
        const props = buildRequestProperties(c, token!, url, 'streamable-http', clientInfo)
        const method = c.req.method

        evictStaleSessions()

        try {
            if (method === 'GET' || method === 'DELETE') {
                const existingSessionId = c.req.header('mcp-session-id')
                if (existingSessionId) {
                    const transport = getStreamableTransport(existingSessionId, props.userHash)
                    if (transport) {
                        if (method === 'DELETE') {
                            await transport.handleRequest(c.req.raw)
                            streamableSessions.delete(existingSessionId)
                            return new Response(null, { status: 200 })
                        }
                        const response = await transport.handleRequest(c.req.raw)
                        return errorHandler(response)
                    }
                }
                if (method === 'DELETE') {
                    return new Response('Session not found', { status: 404 })
                }
            }

            if (method === 'POST') {
                const existingSessionId = c.req.header('mcp-session-id')
                if (existingSessionId) {
                    const transport = getStreamableTransport(existingSessionId, props.userHash)
                    if (transport) {
                        const response = await transport.handleRequest(c.req.raw)
                        return errorHandler(response)
                    }
                }

                if (totalSessionCount() >= MAX_SESSIONS_PER_INSTANCE) {
                    return new Response('Too many active sessions', { status: 503 })
                }

                const mcpServer = new HonoMcpServer(redis, props)
                await mcpServer.init()

                const transport = new WebStandardStreamableHTTPServerTransport({
                    sessionIdGenerator: () => uuidv4(),
                    onsessioninitialized: (sid) => {
                        streamableSessions.set(sid, {
                            transport,
                            createdAt: Date.now(),
                            tokenHash: props.userHash,
                        })
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
        } catch (error) {
            return handleCatchError(error, props.userHash, 'streamable-http')
        }
    }

    // SSE endpoint
    async function handleSseRequest(c: import('hono').Context<HonoEnv>): Promise<Response> {
        const url = new URL(c.req.url)
        const effectiveRegion = getRegionFromRequest(c.req.raw)
        const token = c.req.header('Authorization')?.split(' ')[1]

        const authError = buildAuthErrorResponse(token, url, effectiveRegion, c.req.raw)
        if (authError) {
            return authError
        }

        const clientInfo = await extractClientInfoFromBody(c.req.raw)
        const props = buildRequestProperties(c, token!, url, 'sse', clientInfo)
        const method = c.req.method

        evictStaleSessions()

        try {
            if (method === 'GET') {
                if (totalSessionCount() >= MAX_SESSIONS_PER_INSTANCE) {
                    return new Response('Too many active sessions', { status: 503 })
                }

                const sessionId = uuidv4()
                const mcpServer = new HonoMcpServer(redis, props)
                await mcpServer.init()

                const stream = new ReadableStream({
                    start(controller) {
                        const { transport, start } = createSSEResponseAdapter(controller, () => {
                            sseSessions.delete(sessionId)
                        })
                        sseSessions.set(sessionId, {
                            transport,
                            server: mcpServer,
                            createdAt: Date.now(),
                            tokenHash: props.userHash,
                        })
                        mcpServer.server.connect(transport).then(start)
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
                if (!session || session.tokenHash !== props.userHash) {
                    return new Response('Session not found', { status: 404 })
                }
                const body = await c.req.json()
                await handleSSEPostMessage(session.transport, c.req.raw.headers, c.req.url, body)
                return new Response('Accepted', { status: 202 })
            }

            return new Response('Method not allowed', { status: 405 })
        } catch (error) {
            return handleCatchError(error, props.userHash, 'sse')
        }
    }

    app.all('/mcp', handleMcpRequest)
    app.all('/mcp/*', handleMcpRequest)
    app.all('/sse', handleSseRequest)
    app.all('/sse/*', handleSseRequest)

    app.all('*', (c) => c.notFound())

    return app
}
