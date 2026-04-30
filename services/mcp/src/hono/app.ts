import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'
import type { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js'
import { Hono, type Context } from 'hono'
import { cors } from 'hono/cors'
import { v4 as uuidv4 } from 'uuid'

import { getPostHogClient } from '@/lib/analytics'
import {
    mapErrorToAuthResponse,
    mapKnownErrorMessage,
    validateBearerToken,
} from '@/lib/auth-errors'
import { extractClientInfoFromBody } from '@/lib/mcp-client-info'
import {
    parseRequestProperties,
    type RequestProperties,
    type Transport,
} from '@/lib/request-properties'
import { buildRedirectUrl, getPublicUrl, getRegionFromRequest, matchAuthServerRedirect } from '@/lib/routing'

import type { RedisLike } from './cache/RedisCache'
import {
    ALLOWED_REQUEST_HEADERS,
    AUTH_REDIRECT_PATHS,
    getAuthorizationServerUrl,
    MAX_SESSIONS_PER_INSTANCE,
    MCP_DOCS_URL,
    OAUTH_SCOPES_SUPPORTED,
    SESSION_TTL_MS,
} from './constants'
import { HonoMcpServer } from './mcp-server'
import { SessionRegistry } from './session-registry'
import { createSSEResponseAdapter, handleSSEPostMessage } from './sse-adapter'

import RAW_LANDING_HTML from '../static/landing.html'

const PARSED_LANDING_HTML = RAW_LANDING_HTML.replace('{{DOCS_URL}}', MCP_DOCS_URL)

type HonoEnv = { Variables: { redis: RedisLike } }
type SseEntry = { transport: SSEServerTransport; server: HonoMcpServer }

async function bootMcpServer(redis: RedisLike, props: RequestProperties): Promise<HonoMcpServer> {
    const server = new HonoMcpServer(redis, props)
    await server.init()
    return server
}

function reportInternalError(error: unknown, props: RequestProperties): void {
    try {
        if (error instanceof Error) {
            getPostHogClient().captureException(error, props.userHash, {
                team: 'posthog_ai',
                source: 'mcp_hono_request',
                mcp_transport: props.transport,
            })
        }
    } catch {
        // Never let observability break the request.
    }
}

function handleCatchError(error: unknown, props: RequestProperties): Response {
    const authResponse = mapErrorToAuthResponse(error)
    if (authResponse) {
        return authResponse
    }
    reportInternalError(error, props)
    return new Response('Internal server error', { status: 500 })
}

async function passThrough(response: Response): Promise<Response> {
    if (!response.ok) {
        const body = await response.clone().text()
        const mapped = mapKnownErrorMessage(body)
        if (mapped) {
            return mapped
        }
    }
    return response
}

async function authenticateAndParse(
    c: Context<HonoEnv>,
    transport: Transport
): Promise<{ props: RequestProperties } | { error: Response }> {
    const token = c.req.header('Authorization')?.split(' ')[1]
    const effectiveRegion = getRegionFromRequest(c.req.raw)

    const tokenError = validateBearerToken(token, c.req.raw, effectiveRegion)
    if (tokenError) {
        return { error: tokenError }
    }

    const clientInfo = await extractClientInfoFromBody(c.req.raw)
    return { props: parseRequestProperties(c.req.raw, clientInfo, transport) }
}

export function createApp(redis: RedisLike & { ping?(): Promise<string> }): Hono<HonoEnv> {
    const app = new Hono<HonoEnv>()

    const streamable = new SessionRegistry<WebStandardStreamableHTTPServerTransport>(SESSION_TTL_MS)
    const sse = new SessionRegistry<SseEntry>(SESSION_TTL_MS)

    function totalSessions(): number {
        return streamable.size + sse.size
    }

    function reserveCapacity(): boolean {
        if (totalSessions() < MAX_SESSIONS_PER_INSTANCE) {
            return true
        }
        // At capacity — sweep stale entries before rejecting.
        streamable.compact()
        sse.compact()
        return totalSessions() < MAX_SESSIONS_PER_INSTANCE
    }

    app.use('*', async (c, next) => {
        await next()
        c.header('X-Content-Type-Options', 'nosniff')
        c.header('X-Frame-Options', 'DENY')
    })

    app.use(
        '*',
        cors({
            origin: (origin) => origin,
            allowMethods: ['GET', 'POST', 'DELETE', 'OPTIONS'],
            allowHeaders: [...ALLOWED_REQUEST_HEADERS],
            exposeHeaders: ['mcp-session-id'],
            maxAge: 86400,
        })
    )

    app.use('*', async (c, next) => {
        c.set('redis', redis)
        await next()
    })

    app.get('/', (c) => c.html(PARSED_LANDING_HTML))

    app.get('/.well-known/openai-apps-challenge', (c) =>
        c.text('pRLV9JYbPOF5Dy039v3Rn3-qrMuKqZ2_4SsX9GoL9aU')
    )

    const healthHandler = (c: Context<HonoEnv>): Response =>
        c.json({ status: 'ok' }, 200, { 'Cache-Control': 'no-store' })
    app.get('/health', healthHandler)
    app.get('/healthz', healthHandler)

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

    // OAuth Protected Resource Metadata (RFC 9728).
    // Per RFC 9728, the well-known URL is constructed by inserting
    // /.well-known/oauth-protected-resource between host and resource path.
    const wellKnownHandler = (c: Context<HonoEnv>): Response => {
        const url = new URL(c.req.url)
        const wellKnownPrefix = '/.well-known/oauth-protected-resource'
        const resourcePath = url.pathname.slice(wellKnownPrefix.length) || '/'
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
    app.all('/.well-known/oauth-protected-resource', wellKnownHandler)
    app.all('/.well-known/oauth-protected-resource/*', wellKnownHandler)

    for (const path of AUTH_REDIRECT_PATHS) {
        app.all(path, (c) => {
            const url = new URL(c.req.url)
            const redirect = matchAuthServerRedirect(url.pathname)
            if (!redirect) {
                return c.notFound()
            }
            const authServer = getAuthorizationServerUrl()
            const redirectTo = buildRedirectUrl(authServer, url.pathname, url.search, redirect)
            return c.redirect(redirectTo, redirect.status)
        })
    }

    async function handleMcpRequest(c: Context<HonoEnv>): Promise<Response> {
        const auth = await authenticateAndParse(c, 'streamable-http')
        if ('error' in auth) {
            return auth.error
        }
        const { props } = auth
        const method = c.req.method
        const existingSessionId = c.req.header('mcp-session-id')

        try {
            if (method === 'GET' || method === 'DELETE') {
                const transport = existingSessionId
                    ? streamable.get(existingSessionId, props.userHash)
                    : undefined
                if (transport) {
                    if (method === 'DELETE') {
                        await transport.handleRequest(c.req.raw)
                        streamable.delete(existingSessionId!)
                        return new Response(null, { status: 200 })
                    }
                    return passThrough(await transport.handleRequest(c.req.raw))
                }
                if (method === 'DELETE') {
                    return new Response('Session not found', { status: 404 })
                }
            }

            if (method === 'POST') {
                if (existingSessionId) {
                    const transport = streamable.get(existingSessionId, props.userHash)
                    if (transport) {
                        return passThrough(await transport.handleRequest(c.req.raw))
                    }
                }

                if (!reserveCapacity()) {
                    return new Response('Too many active sessions', { status: 503 })
                }

                const mcpServer = await bootMcpServer(redis, props)
                const transport = new WebStandardStreamableHTTPServerTransport({
                    sessionIdGenerator: () => uuidv4(),
                    onsessioninitialized: (sid) => {
                        streamable.set(sid, transport, props.userHash)
                    },
                })

                transport.onclose = () => {
                    if (transport.sessionId) {
                        streamable.delete(transport.sessionId)
                    }
                }

                await mcpServer.server.connect(transport)
                return passThrough(await transport.handleRequest(c.req.raw))
            }

            return new Response('Method not allowed', { status: 405 })
        } catch (error) {
            return handleCatchError(error, props)
        }
    }

    async function handleSseRequest(c: Context<HonoEnv>): Promise<Response> {
        const auth = await authenticateAndParse(c, 'sse')
        if ('error' in auth) {
            return auth.error
        }
        const { props } = auth
        const method = c.req.method

        try {
            if (method === 'GET') {
                if (!reserveCapacity()) {
                    return new Response('Too many active sessions', { status: 503 })
                }

                const sessionId = uuidv4()
                const mcpServer = await bootMcpServer(redis, props)

                const stream = new ReadableStream({
                    start(controller) {
                        const { transport, start } = createSSEResponseAdapter(controller, () => {
                            sse.delete(sessionId)
                        })
                        sse.set(sessionId, { transport, server: mcpServer }, props.userHash)
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
                const sessionId = new URL(c.req.url).searchParams.get('sessionId')
                if (!sessionId) {
                    return new Response('Missing sessionId', { status: 400 })
                }
                const session = sse.get(sessionId, props.userHash)
                if (!session) {
                    return new Response('Session not found', { status: 404 })
                }
                const body = await c.req.json()
                await handleSSEPostMessage(session.transport, c.req.raw.headers, c.req.url, body)
                return new Response('Accepted', { status: 202 })
            }

            return new Response('Method not allowed', { status: 405 })
        } catch (error) {
            return handleCatchError(error, props)
        }
    }

    app.all('/mcp', handleMcpRequest)
    app.all('/mcp/*', handleMcpRequest)
    app.all('/sse', handleSseRequest)
    app.all('/sse/*', handleSseRequest)

    app.all('*', (c) => c.notFound())

    return app
}
