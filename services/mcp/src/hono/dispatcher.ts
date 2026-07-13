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

import { MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import type { RequestProperties } from '@/lib/request-properties'

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

        const requests = messages.filter(isRequest)
        if (requests.length === 0) {
            return new Response(null, { status: 202 })
        }

        const hasInit = requests.some((r) => r.method === Method.Initialize)
        if (hasInit) {
            props.mcpSessionId = randomUUID()
        }

        const needsState = requests.some((r) => TRACKED_METHODS.has(r.method))
        const state = needsState ? await this.stateResolver.resolve(props) : undefined

        const headers: Record<string, string> = { 'Content-Type': 'application/json' }
        if (props.mcpSessionId) {
            headers['Mcp-Session-Id'] = props.mcpSessionId
        }

        if (!wasArray && requests.length === 1) {
            const result = await this.dispatch(requests[0]!, props, state)
            return new Response(JSON.stringify(result), { status: 200, headers })
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

        try {
            switch (method) {
                case Method.Initialize:
                    return jsonRpcResult(id, await this.handleInitialize(params, props, state!))
                case Method.ToolsList:
                    return jsonRpcResult(id, await this.toolExecutor.handleToolsList(state!))
                case Method.ToolsCall:
                    return jsonRpcResult(id, await this.toolExecutor.handleToolCall(params, state!))
                case Method.ResourcesList:
                    return jsonRpcResult(id, this.resourceCatalog.getResourcesList())
                case Method.ResourcesRead:
                    return jsonRpcResult(id, await this.resourceCatalog.readResource(params))
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

            await this.resourceCatalog.revalidateContextMillResources('initialize')
            const instructions = this.instructionsBuilder.build(state)

            initDurationSeconds.observe(props.requestStartTime ? (Date.now() - props.requestStartTime) / 1000 : 0)
            initTotal.inc({ status: 'success' })

            void trackInitEvent(state)

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
