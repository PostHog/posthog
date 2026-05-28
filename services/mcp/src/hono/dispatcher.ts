/**
 * Shared MCP dispatcher for the Hono server.
 *
 * One class handles both `2025-06-18` and `2026-07-28` traffic. The
 * protocol-specific bits live in `ProtocolStrategy`:
 *
 *   - `preDispatch.validate` — per-request validation
 *     (legacy: noop; v2026: headers + `_meta`).
 *   - `handshake` — the protocol's handshake RPC
 *     (legacy: `initialize`; v2026: `server/discover`).
 *   - `toolCall.dispatchToolsCall` — single-message `tools/call`
 *     (legacy: SSE-upgrade race; v2026: `InputRequiredResult`).
 *   - `toolCall.deliverInboundResponse?` — legacy-only seam for routing
 *     inbound JSON-RPC responses to the session bus. v2026 has no
 *     separate response POSTs.
 *
 * Everything else (`tools/list`, `ping`, `resources/*`, `prompts/*`,
 * JSON-RPC parse and error responses, top-level batch dispatch) is
 * shared here.
 *
 * Two instances are constructed at startup — one per protocol — sharing
 * the underlying catalog, state resolver, and tool executor. The
 * streamable handler selects between them per request.
 */

import { ErrorCode, JSONRPC_VERSION } from '@modelcontextprotocol/sdk/types.js'
import type {
    CallToolRequest,
    GetPromptRequest,
    InitializeRequest,
    JSONRPCMessage,
    JSONRPCRequest,
    ListPromptsRequest,
    ListResourcesRequest,
    ListToolsRequest,
    PingRequest,
    ReadResourceRequest,
} from '@modelcontextprotocol/sdk/types.js'

import type { RequestProperties } from '@/lib/request-properties'

import type { RedisLike } from './cache/RedisCache'
import { getEnv } from './constants'
import { loadGuidelines } from './guidelines-loader'
import { InstructionsBuilder } from './instructions'
import type { ProtocolStrategy } from './protocol-strategy'
import { RequestStateResolver, type ResolvedState } from './request-state-resolver'
import { ResourceCatalog } from './resource-catalog'
import { ToolCatalog } from './tool-catalog'
import { ToolExecutor } from './tool-executor'
import { V2026ProtocolError } from './v2026/errors'

export { McpDispatcher }
export type { ResolvedState } from './request-state-resolver'

const MAX_BATCH_SIZE = 100
const MAX_BODY_BYTES = 1_048_576

const Method = {
    Initialize: 'initialize' as InitializeRequest['method'],
    ToolsList: 'tools/list' as ListToolsRequest['method'],
    ToolsCall: 'tools/call' as CallToolRequest['method'],
    ResourcesList: 'resources/list' as ListResourcesRequest['method'],
    ResourcesRead: 'resources/read' as ReadResourceRequest['method'],
    PromptsList: 'prompts/list' as ListPromptsRequest['method'],
    PromptsGet: 'prompts/get' as GetPromptRequest['method'],
    Ping: 'ping' as PingRequest['method'],
} as const

const TRACKED_METHODS: Set<string> = new Set([Method.Initialize, Method.ToolsList, Method.ToolsCall])

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
    error: { code: number; message: string; data?: Record<string, unknown> }
}
type JsonRpcResponse = JsonRpcResultResponse | JsonRpcErrorResponse

function jsonRpcResult(id: number | string, result: unknown): JsonRpcResultResponse {
    return { jsonrpc: JSONRPC_VERSION, id, result }
}

function jsonRpcMethodError(id: number | string, code: number, message: string): JsonRpcErrorResponse {
    return { jsonrpc: JSONRPC_VERSION, id, error: { code, message } }
}

function jsonRpcErrorResponse(id: unknown, code: number, message: string, httpStatus = 200): Response {
    return new Response(JSON.stringify({ jsonrpc: JSONRPC_VERSION, id: id ?? null, error: { code, message } }), {
        status: httpStatus,
        headers: { 'Content-Type': 'application/json' },
    })
}

export interface SharedDispatcherDeps {
    catalog: ToolCatalog
    resourceCatalog: ResourceCatalog
    stateResolver: RequestStateResolver
    toolExecutor: ToolExecutor
    instructionsBuilder: InstructionsBuilder
}

/**
 * Build the shared dependencies once. Two dispatcher instances (one per
 * protocol) share these — catalog warmup is idempotent and per-request
 * state resolution is stateless across calls.
 */
export function buildSharedDeps(catalog: ToolCatalog, redis: RedisLike): SharedDispatcherDeps {
    const env = getEnv()
    const resourceCatalog = new ResourceCatalog(env)
    const stateResolver = new RequestStateResolver(catalog, redis, env)
    const instructionsBuilder = new InstructionsBuilder(loadGuidelines())
    const toolExecutor = new ToolExecutor(catalog, instructionsBuilder)
    return { catalog, resourceCatalog, stateResolver, toolExecutor, instructionsBuilder }
}

class McpDispatcher {
    private readonly shared: SharedDispatcherDeps
    readonly strategy: ProtocolStrategy

    private warmupPromise: Promise<void> | undefined

    constructor(shared: SharedDispatcherDeps, strategy: ProtocolStrategy) {
        this.shared = shared
        this.strategy = strategy
    }

    async warmup(): Promise<void> {
        this.warmupPromise ??= this.doWarmup()
        await this.warmupPromise
    }

    private async doWarmup(): Promise<void> {
        await this.shared.catalog.warmup()
        await this.shared.resourceCatalog.warmup()
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

        // Per-protocol validation (v2026 checks headers + _meta; legacy noop).
        try {
            await this.strategy.preDispatch.validate(req, body, props)
        } catch (err) {
            return mapProtocolError(err, body)
        }

        const wasArray = Array.isArray(body)
        if (wasArray && !this.strategy.allowBatches) {
            return jsonRpcErrorResponse(
                null,
                ErrorCode.InvalidRequest,
                `JSON-RPC batches are not supported in ${this.strategy.version} protocol`,
                400
            )
        }
        const messages: JSONRPCMessage[] = wasArray ? (body as JSONRPCMessage[]) : [body as JSONRPCMessage]

        if (messages.length > MAX_BATCH_SIZE) {
            return jsonRpcErrorResponse(null, ErrorCode.InvalidRequest, 'Batch too large')
        }

        const requests = messages.filter(isRequest)
        if (requests.length === 0) {
            return new Response(null, { status: 202 })
        }

        const needsState = requests.some(
            (r) => TRACKED_METHODS.has(r.method) || r.method === this.strategy.handshake.method
        )
        const state = needsState ? await this.shared.stateResolver.resolve(props) : undefined

        // Single-message `tools/call` runs through the strategy — that's
        // where elicitation diverges. Batches and other methods take the
        // shared path (server-initiated elicits don't fit batches anyway).
        if (!wasArray && requests.length === 1 && requests[0]!.method === Method.ToolsCall) {
            try {
                return await this.strategy.toolCall.dispatchToolsCall(requests[0]!, props, state!, req.signal)
            } catch (err) {
                return mapProtocolError(err, body)
            }
        }

        try {
            if (!wasArray && requests.length === 1) {
                const result = await this.dispatch(requests[0]!, props, state)
                return jsonResponse(result)
            }
            const results = await Promise.all(requests.map((r) => this.dispatch(r, props, state)))
            return jsonResponse(results)
        } catch (err) {
            return mapProtocolError(err, body)
        }
    }

    private async dispatch(
        request: JSONRPCRequest,
        props: RequestProperties,
        state: ResolvedState | undefined
    ): Promise<JsonRpcResponse> {
        const { id, method, params } = request

        try {
            // The strategy's handshake method (initialize OR server/discover)
            // takes precedence — it owns the shape of the result.
            if (method === this.strategy.handshake.method) {
                const result = await this.strategy.handshake.handle(request, props, state!)
                return jsonRpcResult(id, result)
            }

            switch (method) {
                case Method.ToolsList:
                    return jsonRpcResult(id, await this.shared.toolExecutor.handleToolsList(state!, props))
                case Method.ToolsCall:
                    // Batched tools/call only — single-message hits the
                    // strategy path above. No elicit support in batches.
                    return jsonRpcResult(
                        id,
                        await this.shared.toolExecutor.handleToolCall(
                            params as Record<string, unknown> | undefined,
                            props,
                            state!
                        )
                    )
                case Method.ResourcesList:
                    return jsonRpcResult(id, this.shared.resourceCatalog.getResourcesList())
                case Method.ResourcesRead:
                    return jsonRpcResult(id, this.shared.resourceCatalog.readResource(params))
                case Method.PromptsList:
                    return jsonRpcResult(id, this.shared.resourceCatalog.getPromptsList())
                case Method.PromptsGet:
                    return jsonRpcResult(id, this.shared.resourceCatalog.getPrompt(params))
                case Method.Ping:
                    return jsonRpcResult(id, {})
                default:
                    return jsonRpcMethodError(id, ErrorCode.MethodNotFound, 'Method not found')
            }
        } catch (error) {
            if (error instanceof V2026ProtocolError) {
                return { jsonrpc: JSONRPC_VERSION, id, error: { code: error.code, message: error.message } }
            }
            console.error('[McpDispatcher] Internal error:', error)
            return jsonRpcMethodError(id, ErrorCode.InternalError, 'Internal error')
        }
    }
}

function mapProtocolError(err: unknown, body: unknown): Response {
    if (err instanceof V2026ProtocolError) {
        const id = isRecord(body) && 'id' in body ? (body['id'] as string | number | null) : null
        return new Response(
            JSON.stringify({
                jsonrpc: JSONRPC_VERSION,
                id,
                error: err.data
                    ? { code: err.code, message: err.message, data: err.data }
                    : { code: err.code, message: err.message },
            }),
            { status: err.httpStatus, headers: { 'Content-Type': 'application/json' } }
        )
    }
    throw err
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function jsonResponse(body: unknown): Response {
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
