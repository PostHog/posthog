import {
    ErrorCode,
    JSONRPC_VERSION,
    LATEST_PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
} from '@modelcontextprotocol/sdk/types.js'
import type {
    CallToolRequest,
    GetPromptRequest,
    InitializeRequest,
    InitializeResult,
    JSONRPCMessage,
    JSONRPCRequest,
    ListPromptsRequest,
    ListResourcesRequest,
    ListToolsRequest,
    PingRequest,
    ReadResourceRequest,
} from '@modelcontextprotocol/sdk/types.js'
import GUIDELINES from '@shared/guidelines.md'
import { randomUUID } from 'node:crypto'

import { mapErrorToAuthResponse } from '@/lib/auth-errors'
import { MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import type { RequestProperties } from '@/lib/request-properties'
import {
    isModernRequest,
    META_SERVER_INFO,
    MODERN_PROTOCOL_VERSIONS,
    parseRequestProtocolMeta,
    readProtocolHeaders,
    SERVER_DISCOVER_METHOD,
    STATELESS_PROTOCOL_VERSION,
    validateModernRequest,
} from '@/lib/stateless-protocol'

import { trackInitEvent } from './analytics'
import type { RedisLike } from './cache/RedisCache'
import { getEnv } from './constants'
import { InstructionsBuilder } from './instructions'
import { initDurationSeconds, initTotal } from './metrics'
import { RequestStateResolver, type ResolvedState } from './request-state-resolver'
import { ResourceCatalog } from './resource-catalog'
import { ToolCatalog } from './tool-catalog'
import { ToolExecutor } from './tool-executor'

export { McpDispatcher }
export type { ResolvedState } from './request-state-resolver'

const MAX_BATCH_SIZE = 100
const MAX_BODY_BYTES = 1_048_576

const Method = {
    Initialize: 'initialize' as InitializeRequest['method'],
    Discover: SERVER_DISCOVER_METHOD,
    ToolsList: 'tools/list' as ListToolsRequest['method'],
    ToolsCall: 'tools/call' as CallToolRequest['method'],
    ResourcesList: 'resources/list' as ListResourcesRequest['method'],
    ResourcesRead: 'resources/read' as ReadResourceRequest['method'],
    PromptsList: 'prompts/list' as ListPromptsRequest['method'],
    PromptsGet: 'prompts/get' as GetPromptRequest['method'],
    Ping: 'ping' as PingRequest['method'],
} as const

const TRACKED_METHODS: Set<string> = new Set([Method.Initialize, Method.Discover, Method.ToolsList, Method.ToolsCall])

// Results the 2026-07-28 spec types as CacheableResult (required ttlMs +
// cacheScope). Everything here varies per token (scopes, flags, staff gating)
// or per user (discover instructions), so shared intermediaries must not cache.
const CACHEABLE_METHODS: Set<string> = new Set([
    Method.Discover,
    Method.ToolsList,
    Method.ResourcesList,
    Method.ResourcesRead,
    Method.PromptsList,
])
// ttlMs: 0 is the spec-compliant "don't serve from cache" (both fields are
// required on CacheableResult). Nonzero TTLs are production-only: SDK clients
// honor the hint with a built-in response cache, so locally it would serve a
// stale tools/list while iterating on tool definitions — and with
// listChanged: false the TTL is the client's only freshness signal.
const CACHEABLE_RESULT_TTL_MS = process.env.NODE_ENV === 'production' ? 60_000 : 0

const METHOD_NOT_FOUND = Symbol('method-not-found')

const SERVER_CAPABILITIES = {
    tools: { listChanged: false },
    resources: { listChanged: false },
    prompts: { listChanged: false },
} as const

function isRequest(msg: JSONRPCMessage): msg is JSONRPCRequest {
    return (
        typeof msg === 'object' &&
        msg !== null &&
        'id' in msg &&
        typeof (msg as { method?: unknown }).method === 'string'
    )
}

type JsonRpcResultResponse = { jsonrpc: typeof JSONRPC_VERSION; id: number | string; result: unknown }
type JsonRpcErrorResponse = {
    jsonrpc: typeof JSONRPC_VERSION
    id: number | string
    error: { code: number; message: string; data?: unknown }
}
type JsonRpcResponse = JsonRpcResultResponse | JsonRpcErrorResponse

function jsonRpcResult(id: number | string, result: unknown): JsonRpcResultResponse {
    return { jsonrpc: JSONRPC_VERSION, id, result }
}

function jsonRpcMethodError(id: number | string, code: number, message: string, data?: unknown): JsonRpcErrorResponse {
    return { jsonrpc: JSONRPC_VERSION, id, error: { code, message, ...(data !== undefined ? { data } : {}) } }
}

function jsonRpcErrorResponse(id: unknown, code: number, message: string, data?: unknown, status = 200): Response {
    return new Response(
        JSON.stringify({
            jsonrpc: JSONRPC_VERSION,
            id: id ?? null,
            error: { code, message, ...(data !== undefined ? { data } : {}) },
        }),
        {
            status,
            headers: { 'Content-Type': 'application/json' },
        }
    )
}

class McpDispatcher {
    private readonly catalog: ToolCatalog
    private readonly resourceCatalog: ResourceCatalog
    private readonly stateResolver: RequestStateResolver
    private readonly toolExecutor: ToolExecutor
    private readonly instructionsBuilder: InstructionsBuilder

    private warmupPromise: Promise<void> | undefined

    constructor(catalog: ToolCatalog, redis: RedisLike) {
        const env = getEnv()
        this.catalog = catalog
        this.resourceCatalog = new ResourceCatalog(env, redis)
        this.stateResolver = new RequestStateResolver(catalog, redis, env)
        this.instructionsBuilder = new InstructionsBuilder(GUIDELINES)
        this.toolExecutor = new ToolExecutor(catalog, this.instructionsBuilder)
    }

    async warmup(): Promise<void> {
        this.warmupPromise ??= this.doWarmup()
        await this.warmupPromise
    }

    private async doWarmup(): Promise<void> {
        await this.catalog.warmup()
        await this.resourceCatalog.warmup()
    }

    async handleRequest(req: Request, props: RequestProperties): Promise<Response> {
        const contentLength = req.headers.get('content-length')
        if (contentLength && parseInt(contentLength, 10) > MAX_BODY_BYTES) {
            return jsonRpcErrorResponse(null, ErrorCode.InvalidRequest, 'Request body too large')
        }

        let body: unknown
        try {
            body = await req.json()
        } catch {
            return jsonRpcErrorResponse(null, ErrorCode.ParseError, 'Parse error: Invalid JSON')
        }

        const wasArray = Array.isArray(body)
        const messages: JSONRPCMessage[] = wasArray ? (body as JSONRPCMessage[]) : [body as JSONRPCMessage]

        if (messages.length > MAX_BATCH_SIZE) {
            return jsonRpcErrorResponse(null, ErrorCode.InvalidRequest, 'Batch too large')
        }

        // SEP-2243 header validation, before any dispatch: modern messages must
        // carry matching operation headers, and (since JSON-RPC batching was
        // removed in 2025-06-18) can never arrive inside an array. Legacy
        // traffic takes neither branch and keeps its exact wire behavior.
        const protocolHeaders = readProtocolHeaders(req.headers)
        let singleModern = false
        if (wasArray) {
            const batchHasModern = messages.some((m) =>
                isModernRequest(protocolHeaders, parseRequestProtocolMeta((m as { params?: unknown }).params))
            )
            if (batchHasModern) {
                return jsonRpcErrorResponse(
                    null,
                    ErrorCode.InvalidRequest,
                    `JSON-RPC batching is not supported by protocol version ${STATELESS_PROTOCOL_VERSION}`,
                    undefined,
                    400
                )
            }
        } else {
            const message = messages[0]! as { id?: number | string; method?: unknown; params?: unknown }
            singleModern = isModernRequest(protocolHeaders, parseRequestProtocolMeta(message.params))
            if (singleModern) {
                const validationError = validateModernRequest(protocolHeaders, message)
                if (validationError) {
                    return jsonRpcErrorResponse(
                        message.id ?? null,
                        validationError.code,
                        validationError.message,
                        validationError.data,
                        400
                    )
                }
            }
        }

        const requests = messages.filter(isRequest)
        if (requests.length === 0) {
            return new Response(null, { status: 202 })
        }

        // Only the legacy dialect mints sessions — modern `initialize` is a
        // removed RPC and gets method-not-found in dispatch.
        const hasInit = !singleModern && requests.some((r) => r.method === Method.Initialize)
        if (hasInit) {
            props.mcpSessionId = randomUUID()
        }

        const needsState = requests.some((r) => TRACKED_METHODS.has(r.method))
        let state: ResolvedState | undefined
        try {
            state = needsState ? await this.stateResolver.resolve(props) : undefined
        } catch (error) {
            // A failed resolution still fails the handshake for the client, so count
            // it in mcp_init_total — otherwise MCPServerHighInitErrorRate only sees
            // failures past this point. Auth failures (expired tokens, missing scopes)
            // are client-side and dominate resolution errors, so they get their own
            // status to keep the alert on `status="error"` meaningful. The rethrow
            // surfaces as a 401/403/500 upstream via handleCatchError.
            if (hasInit) {
                initTotal.inc({ status: mapErrorToAuthResponse(error) ? 'auth_error' : 'error' })
            }
            throw error
        }

        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (props.mcpSessionId) {
            headers['Mcp-Session-Id'] = props.mcpSessionId
        }

        if (!wasArray && requests.length === 1) {
            const result = await this.dispatch(requests[0]!, props, state)
            // SEP-2575: unsupported RPCs get HTTP 404 in the modern dialect.
            const status =
                singleModern && 'error' in result && result.error.code === ErrorCode.MethodNotFound ? 404 : 200
            return new Response(JSON.stringify(result), { status, headers })
        }

        const results = await Promise.all(requests.map((r) => this.dispatch(r, props, state)))
        return new Response(JSON.stringify(results), { status: 200, headers })
    }

    private async dispatch(
        request: JSONRPCRequest,
        props: RequestProperties,
        state: ResolvedState | undefined
    ): Promise<JsonRpcResponse> {
        const { id, method, params } = request

        // Version and header validation for modern requests happens in
        // `handleRequest` before dispatch; here `_meta` only picks the dialect.
        const protocolMeta = parseRequestProtocolMeta(params)
        const stateless = protocolMeta.protocolVersion === STATELESS_PROTOCOL_VERSION

        try {
            const result = await this.dispatchMethod(method, params, props, state, stateless)
            if (result === METHOD_NOT_FOUND) {
                return jsonRpcMethodError(id, ErrorCode.MethodNotFound, 'Method not found')
            }
            return jsonRpcResult(id, stateless ? this.decorateStatelessResult(method, result) : result)
        } catch (error) {
            console.error('[McpDispatcher] Internal error:', error)
            return jsonRpcMethodError(id, ErrorCode.InternalError, 'Internal error')
        }
    }

    /** Returns the raw result for the method, or `METHOD_NOT_FOUND` for unknown methods. */
    private async dispatchMethod(
        method: string,
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState | undefined,
        stateless: boolean
    ): Promise<unknown> {
        // SEP-2575 removed `initialize` and `ping` from the modern dialect.
        if (stateless && (method === Method.Initialize || method === Method.Ping)) {
            return METHOD_NOT_FOUND
        }
        switch (method) {
            case Method.Initialize:
                return await this.handleInitialize(params, props, state!)
            case Method.Discover:
                return await this.handleDiscover(props, state!)
            case Method.ToolsList:
                return await this.toolExecutor.handleToolsList(state!)
            case Method.ToolsCall:
                return await this.toolExecutor.handleToolCall(params, state!)
            case Method.ResourcesList:
                return this.resourceCatalog.getResourcesList()
            case Method.ResourcesRead:
                return await this.resourceCatalog.readResource(params)
            case Method.PromptsList:
                return this.resourceCatalog.getPromptsList()
            case Method.PromptsGet:
                return this.resourceCatalog.getPrompt(params)
            case Method.Ping:
                return {}
            default:
                return METHOD_NOT_FOUND
        }
    }

    // 2026-07-28 results carry `resultType`, the server's identity in `_meta`,
    // and (for CacheableResult methods) client-cache freshness hints. Legacy
    // requests keep the exact pre-existing wire shape.
    private decorateStatelessResult(method: string, result: unknown): unknown {
        const base = result && typeof result === 'object' ? (result as Record<string, unknown>) : {}
        const existingMeta =
            base._meta && typeof base._meta === 'object' ? (base._meta as Record<string, unknown>) : undefined
        return {
            ...base,
            resultType: 'complete',
            ...(CACHEABLE_METHODS.has(method)
                ? { ttlMs: CACHEABLE_RESULT_TTL_MS, cacheScope: 'private' as const }
                : {}),
            _meta: {
                ...existingMeta,
                [META_SERVER_INFO]: { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
            },
        }
    }

    private async handleInitialize(
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState
    ): Promise<InitializeResult> {
        // A client that sends `initialize` is speaking the legacy dialect, so
        // negotiation stays within the SDK's pre-stateless version list — a
        // 2026-07-28-capable client falling back here gets the newest legacy
        // version, matching the spec's fallback-negotiation behavior.
        const requestedVersion = (params?.protocolVersion as string) ?? LATEST_PROTOCOL_VERSION
        const protocolVersion = SUPPORTED_PROTOCOL_VERSIONS.includes(requestedVersion)
            ? requestedVersion
            : LATEST_PROTOCOL_VERSION

        const instructions = await this.recordDiscoveryRequest('initialize', props, state)

        return {
            protocolVersion,
            capabilities: SERVER_CAPABILITIES,
            serverInfo: { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
            ...(instructions ? { instructions } : {}),
        }
    }

    // `server/discover` is the stateless counterpart of `initialize`: same
    // capability/instruction payload, but no version negotiation (each request
    // self-describes) and no session minting. Server identity rides in the
    // result `_meta` via `decorateStatelessResult`.
    private async handleDiscover(props: RequestProperties, state: ResolvedState): Promise<Record<string, unknown>> {
        const instructions = await this.recordDiscoveryRequest('discover', props, state)
        return {
            // Modern versions only: legacy support is reachable solely through
            // the `initialize` fallback, and legacy clients never call discover.
            // Advertising legacy versions here would invite modern clients to
            // select one via `_meta`, which we reject.
            supportedVersions: [...MODERN_PROTOCOL_VERSIONS],
            capabilities: SERVER_CAPABILITIES,
            serverInfo: { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
            ...(instructions ? { instructions } : {}),
        }
    }

    /**
     * Shared side effects of the two discovery entry points (`initialize` and
     * `server/discover`): context-mill revalidation, init metrics, and the
     * `$mcp_initialize` analytics event. Returns the per-user instructions.
     */
    private async recordDiscoveryRequest(
        source: 'initialize' | 'discover',
        props: RequestProperties,
        state: ResolvedState
    ): Promise<string | undefined> {
        try {
            await this.resourceCatalog.revalidateContextMillResources(source)
            const instructions = this.instructionsBuilder.build(state)

            initDurationSeconds.observe(props.requestStartTime ? (Date.now() - props.requestStartTime) / 1000 : 0)
            initTotal.inc({ status: 'success' })

            void trackInitEvent(state)

            return instructions
        } catch (error) {
            initTotal.inc({ status: mapErrorToAuthResponse(error) ? 'auth_error' : 'error' })
            throw error
        }
    }
}
