import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'
import {
    CallToolRequestSchema,
    type CallToolResult,
    ListToolsRequestSchema,
    type Tool,
} from '@modelcontextprotocol/sdk/types.js'
import { z } from 'zod'

import { MCP_CLIENT_IP_HEADERS, signedClientIpHeaders } from '@/lib/client-ip-signature'
import { getCustomApiBaseUrl, getUserAgent, MCP_DOCS_URL, MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import { DocsSearchBody } from '@/generated/docs/api'
import { isFeatureFlagEnabled, resolveFeatureFlagOverrides } from '@/lib/posthog/flags'
import { sanitizeHeaderValue } from '@/lib/utils'
import { getToolDefinition } from '@/tools/toolDefinitions'

import type { Lifecycle } from './app'
import type { RedisLike } from './cache/RedisCache'
import { resolveClientIp } from './client-ip'
import { getClientIpSigningKeys, getEdgeClientIpSigningKeys } from './constants'
import { toolCallsTotal } from './metrics'
import { buildRateLimitResponse, type RateLimitConfig, RateLimiter } from './rate-limiter'
import type { HonoCtx } from './types'

export const PUBLIC_DOCS_MCP_FEATURE_FLAG = 'mcp-public-docs-search'

const DOCS_SEARCH_TOOL = 'docs-search'
// The flag is an on/off switch for the whole endpoint, so one fixed distinct ID evaluates it.
const FLAG_DISTINCT_ID = 'mcp-public-docs'
const FLAG_CACHE_TTL_MS = 60_000

// Every JSON-RPC message counts, so a session spends a few requests on the handshake.
// The API has its own per-IP limit on the searches themselves.
const PUBLIC_BURST_LIMIT: RateLimitConfig = { scope: 'mcp_public_docs_burst', limit: 60, windowSeconds: 60 }
const PUBLIC_SUSTAINED_LIMIT: RateLimitConfig = { scope: 'mcp_public_docs_sustained', limit: 600, windowSeconds: 3600 }

const INSTRUCTIONS = `This is the public PostHog docs server. It needs no account and can only search the PostHog documentation.
To query analytics, feature flags, experiments, errors and other data in a PostHog project, connect the full PostHog MCP server. See ${MCP_DOCS_URL}.`

const docsSearchSchema = DocsSearchBody()

function buildDocsSearchTool(): Tool {
    const definition = getToolDefinition(DOCS_SEARCH_TOOL)
    return {
        name: DOCS_SEARCH_TOOL,
        title: definition.title,
        description: definition.description,
        inputSchema: z.toJSONSchema(docsSearchSchema, { io: 'input' }) as Tool['inputSchema'],
        annotations: { title: definition.title, ...definition.annotations },
    }
}

function getApiBaseUrl(): string {
    const customApiBaseUrl = getCustomApiBaseUrl()
    if (customApiBaseUrl) {
        return customApiBaseUrl
    }
    if (process.env.NODE_ENV === 'production') {
        throw new Error('POSTHOG_API_BASE_URL must be set in production')
    }
    return 'http://localhost:8010'
}

function errorResult(text: string): CallToolResult {
    return { content: [{ type: 'text', text }], isError: true }
}

async function searchDocs(
    query: string,
    clientIp: string | undefined,
    clientUserAgent: string | undefined
): Promise<CallToolResult> {
    const signingKeys = getClientIpSigningKeys()
    const response = await fetch(`${getApiBaseUrl()}/api/public_docs_search/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'User-Agent': getUserAgent({ clientUserAgent }),
            'X-PostHog-Client': 'mcp',
            ...(clientIp ? await signedClientIpHeaders(MCP_CLIENT_IP_HEADERS, signingKeys, clientIp) : {}),
        },
        body: JSON.stringify({ query }),
    })
    if (response.status === 429) {
        return errorResult('Docs search is rate limited. Wait a minute before you search again.')
    }
    if (!response.ok) {
        return errorResult('Docs search failed. Do not immediately retry the tool call.')
    }
    const body = (await response.json()) as { content: string }
    return { content: [{ type: 'text', text: body.content }] }
}

/**
 * Serves `/docs/mcp`: an MCP server that needs no auth and has only `docs-search`, so agents
 * can find PostHog before their user has an account. It is separate from `/mcp` because a
 * client that gets no 401 there never starts the OAuth flow.
 */
export class PublicDocsMcpHandler {
    private readonly rateLimiter: RateLimiter
    private tool: Tool | undefined
    private flagCache: { enabled: boolean; expiresAt: number } | undefined

    constructor(
        redis: RedisLike,
        private readonly lifecycle: Lifecycle
    ) {
        this.rateLimiter = new RateLimiter(redis, [PUBLIC_BURST_LIMIT, PUBLIC_SUSTAINED_LIMIT])
    }

    fetch = async (c: HonoCtx): Promise<Response> => {
        if (c.req.method !== 'POST') {
            return new Response('Method not allowed', { status: 405 })
        }
        if (this.lifecycle.shuttingDown) {
            return new Response('Server shutting down', { status: 503 })
        }
        if (!(await this.isEnabled())) {
            return c.notFound() as unknown as Response
        }

        const { ip } = await resolveClientIp(c.req.raw.headers, getEdgeClientIpSigningKeys())
        // Requests with no resolved IP share one bucket, so a missing edge signature fails closed.
        const rateLimit = await this.rateLimiter.check(`ip:${ip ?? 'unknown'}`)
        if (rateLimit && !rateLimit.allowed) {
            return buildRateLimitResponse(rateLimit)
        }

        const server = this.createServer(ip, sanitizeHeaderValue(c.req.header('user-agent')))
        const transport = new WebStandardStreamableHTTPServerTransport({
            sessionIdGenerator: undefined,
            enableJsonResponse: true,
        })
        await server.connect(transport)
        try {
            return await transport.handleRequest(c.req.raw)
        } finally {
            void server.close()
        }
    }

    private async isEnabled(): Promise<boolean> {
        const override = resolveFeatureFlagOverrides()[PUBLIC_DOCS_MCP_FEATURE_FLAG]
        if (override !== undefined) {
            return override === true
        }
        const now = Date.now()
        if (!this.flagCache || this.flagCache.expiresAt <= now) {
            const enabled = await isFeatureFlagEnabled(PUBLIC_DOCS_MCP_FEATURE_FLAG, FLAG_DISTINCT_ID)
            this.flagCache = { enabled, expiresAt: now + FLAG_CACHE_TTL_MS }
        }
        return this.flagCache.enabled
    }

    private createServer(clientIp: string | undefined, clientUserAgent: string | undefined): Server {
        const server = new Server(
            { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
            { capabilities: { tools: {} }, instructions: INSTRUCTIONS }
        )
        this.tool ??= buildDocsSearchTool()
        const tool = this.tool

        server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [tool] }))
        server.setRequestHandler(CallToolRequestSchema, async (request): Promise<CallToolResult> => {
            if (request.params.name !== DOCS_SEARCH_TOOL) {
                return errorResult(`Unknown tool: ${request.params.name}. This server only has ${DOCS_SEARCH_TOOL}.`)
            }
            const args = docsSearchSchema.safeParse(request.params.arguments ?? {})
            if (!args.success) {
                return errorResult(`Invalid arguments: ${z.prettifyError(args.error)}`)
            }
            try {
                const result = await searchDocs(args.data.query, clientIp, clientUserAgent)
                toolCallsTotal.inc({ tool: 'public:docs-search', status: result.isError ? 'error' : 'success' })
                return result
            } catch (error) {
                console.error('[PublicDocsMcpHandler] docs search failed:', error)
                toolCallsTotal.inc({ tool: 'public:docs-search', status: 'error' })
                return errorResult('Docs search failed. Do not immediately retry the tool call.')
            }
        })
        return server
    }
}
