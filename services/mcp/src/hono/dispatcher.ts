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

import { MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import type { RequestProperties } from '@/lib/request-properties'

import { trackInitEvent } from './analytics'
import type { RedisLike } from './cache/RedisCache'
import { getEnv } from './constants'
import { ElicitBinding } from './elicit-binding'
import { InstructionsBuilder } from './instructions'
import { initDurationSeconds, initTotal } from './metrics'
import { RequestStateResolver, type ResolvedState } from './request-state-resolver'
import { ResourceCatalog } from './resource-catalog'
import { type BusAwaitMetrics, RedisPollingSessionResponseBus, type SessionResponseBus } from './session-bus'
import { createSseResponse, type SseResponseHandle } from './sse-response'
import { ToolCatalog } from './tool-catalog'
import { ToolExecutor } from './tool-executor'

export { McpDispatcher }
export type { ResolvedState } from './request-state-resolver'

function loadGuidelines(): string {
    try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const mod = require('@shared/guidelines.md')
        return typeof mod === 'string' ? mod : (mod?.default ?? '')
    } catch {
        // @shared alias only resolves in the esbuild production bundle.
        // Fall back to reading from disk (works in Vitest/test contexts).
    }
    try {
        const fs = require('node:fs')
        const path = require('node:path')
        return fs.readFileSync(path.resolve(process.cwd(), 'shared/guidelines.md'), 'utf-8')
    } catch {
        return ''
    }
}

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
    error: { code: number; message: string }
}
type JsonRpcResponse = JsonRpcResultResponse | JsonRpcErrorResponse

function jsonRpcResult(id: number | string, result: unknown): JsonRpcResultResponse {
    return { jsonrpc: JSONRPC_VERSION, id, result }
}

function jsonRpcMethodError(id: number | string, code: number, message: string): JsonRpcErrorResponse {
    return { jsonrpc: JSONRPC_VERSION, id, error: { code, message } }
}

function jsonRpcErrorResponse(id: unknown, code: number, message: string): Response {
    return new Response(JSON.stringify({ jsonrpc: JSONRPC_VERSION, id: id ?? null, error: { code, message } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
    })
}

export interface McpDispatcherOptions {
    /**
     * Cross-pod session bus. Defaults to a Redis-polling bus over the same
     * `RedisLike` client. Tests can inject `InMemorySessionResponseBus`.
     */
    sessionBus?: SessionResponseBus
    /**
     * Per-await metrics adapter (e.g. Prometheus). Defaults to no-op.
     */
    busMetrics?: BusAwaitMetrics
}

class McpDispatcher {
    private readonly catalog: ToolCatalog
    private readonly resourceCatalog: ResourceCatalog
    private readonly stateResolver: RequestStateResolver
    private readonly toolExecutor: ToolExecutor
    private readonly instructionsBuilder: InstructionsBuilder
    private readonly sessionBus: SessionResponseBus
    private readonly busMetrics: BusAwaitMetrics | undefined

    private warmupPromise: Promise<void> | undefined

    constructor(catalog: ToolCatalog, redis: RedisLike, options: McpDispatcherOptions = {}) {
        const env = getEnv()
        this.catalog = catalog
        this.resourceCatalog = new ResourceCatalog(env)
        this.stateResolver = new RequestStateResolver(catalog, redis, env)
        this.instructionsBuilder = new InstructionsBuilder(loadGuidelines())
        this.toolExecutor = new ToolExecutor(catalog, this.instructionsBuilder)
        this.sessionBus = options.sessionBus ?? new RedisPollingSessionResponseBus(redis)
        this.busMetrics = options.busMetrics
    }

    /** Test accessor — exposes the bus so tests can deliver elicit responses. */
    get bus(): SessionResponseBus {
        return this.sessionBus
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

        const requests = messages.filter(isRequest)
        if (requests.length === 0) {
            return new Response(null, { status: 202 })
        }

        const needsState = requests.some((r) => TRACKED_METHODS.has(r.method))
        const state = needsState ? await this.stateResolver.resolve(props) : undefined

        // Single-message tools/call can upgrade to SSE if the tool handler
        // calls `context.elicit()`. Batches and other methods stay on the
        // plain JSON path — server-initiated elicits don't fit the batch
        // request/response shape and aren't valid for non-tool methods.
        if (!wasArray && requests.length === 1 && requests[0]!.method === Method.ToolsCall) {
            return await this.dispatchToolsCallWithMaybeSse(requests[0]!, props, state!, req.signal)
        }

        if (!wasArray && requests.length === 1) {
            const result = await this.dispatch(requests[0]!, props, state)
            return new Response(JSON.stringify(result), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
        }

        const results = await Promise.all(requests.map((r) => this.dispatch(r, props, state)))
        return new Response(JSON.stringify(results), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
        })
    }

    /**
     * Dispatch a single `tools/call` request that may surface an elicit.
     *
     * Runs the tool handler concurrently with a watcher for the first elicit.
     * Whichever finishes first decides the response shape:
     * - **Handler completes first** → return plain JSON, exactly as the
     *   pre-elicit code path did. Zero extra cost when no elicit fires.
     * - **First elicit fires first** → return the SSE response immediately
     *   (already carrying the `elicitation/create` message). Continue
     *   awaiting the handler in the background; when it resolves, write
     *   the final JSONRPC result to the SSE stream and close it.
     */
    private async dispatchToolsCallWithMaybeSse(
        request: JSONRPCRequest,
        props: RequestProperties,
        state: ResolvedState,
        requestSignal: AbortSignal
    ): Promise<Response> {
        const { id, params } = request

        const binding = new ElicitBinding({
            bus: this.sessionBus,
            createSseHandle: async () => createSseResponse(),
            requestSignal,
            ...(this.busMetrics !== undefined ? { gatewayOptions: { metrics: this.busMetrics } } : {}),
        })
        state.reqCtx.setElicitBinding(binding)

        type HandlerOutcome = { kind: 'success'; value: unknown } | { kind: 'error'; error: unknown }
        const handlerPromise: Promise<HandlerOutcome> = this.toolExecutor
            .handleToolCall(params, props, state)
            .then((value): HandlerOutcome => ({ kind: 'success', value }))
            .catch((error): HandlerOutcome => ({ kind: 'error', error }))

        // Wait for whichever happens first.
        const winner = await Promise.race([
            handlerPromise.then(() => 'handler' as const),
            binding.firstElicit.then(() => 'elicit' as const),
        ])

        if (winner === 'handler') {
            const outcome = await handlerPromise
            const result = this.buildToolsCallJsonRpcResponse(id, outcome)
            return new Response(JSON.stringify(result), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
        }

        // SSE path — the binding already wrote `elicitation/create` to the
        // writer. Hand the response back to the client now; flush the
        // handler's eventual result asynchronously.
        const sseHandle = binding.getSseHandle()
        if (!sseHandle) {
            // Should never happen: firstElicit resolved but no handle was
            // recorded. Treat as internal error.
            const fallback = jsonRpcMethodError(id, ErrorCode.InternalError, 'Internal error')
            return new Response(JSON.stringify(fallback), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
        }

        void this.finalizeSseResponse(sseHandle, id, handlerPromise)
        return sseHandle.response
    }

    /**
     * Wait for the tool handler to complete, then write the final JSONRPC
     * result (or error) to the SSE writer and close the stream. Errors
     * during the writes themselves are swallowed — the client has already
     * disconnected at that point.
     */
    private async finalizeSseResponse(
        sseHandle: SseResponseHandle,
        id: number | string,
        handlerPromise: Promise<{ kind: 'success'; value: unknown } | { kind: 'error'; error: unknown }>
    ): Promise<void> {
        try {
            const outcome = await handlerPromise
            const result = this.buildToolsCallJsonRpcResponse(id, outcome)
            await sseHandle.writer.write(result)
        } catch (error) {
            console.error('[McpDispatcher] SSE finalize failed:', error)
        } finally {
            try {
                await sseHandle.writer.close()
            } catch {
                /* already closed */
            }
        }
    }

    private buildToolsCallJsonRpcResponse(
        id: number | string,
        outcome: { kind: 'success'; value: unknown } | { kind: 'error'; error: unknown }
    ): JsonRpcResponse {
        if (outcome.kind === 'success') {
            return jsonRpcResult(id, outcome.value)
        }
        console.error('[McpDispatcher] Internal error:', outcome.error)
        return jsonRpcMethodError(id, ErrorCode.InternalError, 'Internal error')
    }

    private async dispatch(
        request: JSONRPCRequest,
        props: RequestProperties,
        state: ResolvedState | undefined
    ): Promise<JsonRpcResponse> {
        const { id, method, params } = request

        try {
            switch (method) {
                case Method.Initialize:
                    return jsonRpcResult(id, await this.handleInitialize(params, props, state!))
                case Method.ToolsList:
                    return jsonRpcResult(id, await this.toolExecutor.handleToolsList(state!, props))
                case Method.ToolsCall:
                    return jsonRpcResult(id, await this.toolExecutor.handleToolCall(params, props, state!))
                case Method.ResourcesList:
                    return jsonRpcResult(id, this.resourceCatalog.getResourcesList())
                case Method.ResourcesRead:
                    return jsonRpcResult(id, this.resourceCatalog.readResource(params))
                case Method.PromptsList:
                    return jsonRpcResult(id, this.resourceCatalog.getPromptsList())
                case Method.PromptsGet:
                    return jsonRpcResult(id, this.resourceCatalog.getPrompt(params))
                case Method.Ping:
                    return jsonRpcResult(id, {})
                default:
                    return jsonRpcMethodError(id, ErrorCode.MethodNotFound, 'Method not found')
            }
        } catch (error) {
            console.error('[McpDispatcher] Internal error:', error)
            return jsonRpcMethodError(id, ErrorCode.InternalError, 'Internal error')
        }
    }

    private async handleInitialize(
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState
    ): Promise<InitializeResult> {
        try {
            const requestedVersion = (params?.protocolVersion as string) ?? LATEST_PROTOCOL_VERSION
            const protocolVersion = SUPPORTED_PROTOCOL_VERSIONS.includes(requestedVersion)
                ? requestedVersion
                : LATEST_PROTOCOL_VERSION

            const instructions = await this.instructionsBuilder.build(props, state)

            initDurationSeconds.observe(props.requestStartTime ? (Date.now() - props.requestStartTime) / 1000 : 0)
            initTotal.inc({ status: 'success' })

            void trackInitEvent(props, state)

            return {
                protocolVersion,
                capabilities: {
                    tools: { listChanged: false },
                    resources: { listChanged: false },
                    prompts: { listChanged: false },
                },
                serverInfo: { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
                ...(instructions ? { instructions } : {}),
            }
        } catch (error) {
            initTotal.inc({ status: 'error' })
            throw error
        }
    }
}
