import { LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS } from '@modelcontextprotocol/sdk/types.js'

import type { RequestProperties } from '@/lib/request-properties'

import type { RedisLike } from './cache/RedisCache'
import { getEnv } from './constants'
import { initDurationSeconds } from './metrics'
import { ToolCatalog } from './tool-catalog'

import { AnalyticsBridge } from './analytics-bridge'
import { InstructionsBuilder } from './instructions'
import { RequestStateResolver } from './request-state-resolver'
import { ResourceCatalog } from './resource-catalog'
import { ToolExecutor } from './tool-executor'
import {
    type JsonRpcMessage,
    type JsonRpcRequest,
    type MethodHandlerCallbacks,
    type ResolvedState,
    isRequest,
    isTrackedMethod,
    jsonRpcError,
} from './protocol-types'

export { McpDispatcher }
export type { ResolvedState } from './protocol-types'

const MAX_BATCH_SIZE = 100
const MAX_BODY_BYTES = 1_048_576

class McpDispatcher {
    private readonly catalog: ToolCatalog
    private readonly resourceCatalog: ResourceCatalog
    private readonly stateResolver: RequestStateResolver
    private readonly analyticsBridge: AnalyticsBridge
    private readonly toolExecutor: ToolExecutor
    private readonly instructionsBuilder: InstructionsBuilder

    private _warmupPromise: Promise<void> | undefined

    constructor(catalog: ToolCatalog, redis: RedisLike) {
        const env = getEnv()
        this.catalog = catalog
        this.resourceCatalog = new ResourceCatalog(env)
        this.stateResolver = new RequestStateResolver(catalog, redis, env)
        this.analyticsBridge = new AnalyticsBridge(env)
        this.instructionsBuilder = new InstructionsBuilder()
        this.toolExecutor = new ToolExecutor(catalog, this.instructionsBuilder)
    }

    async warmup(): Promise<void> {
        this._warmupPromise ??= this._doWarmup()
        await this._warmupPromise
    }

    private async _doWarmup(): Promise<void> {
        await this.catalog.warmup()
        await this.resourceCatalog.warmup()
    }

    async handleRequest(req: Request, props: RequestProperties): Promise<Response> {
        const contentLength = req.headers.get('content-length')
        if (contentLength && parseInt(contentLength, 10) > MAX_BODY_BYTES) {
            return jsonRpcError(null, -32600, 'Request body too large')
        }

        let body: unknown
        try {
            body = await req.json()
        } catch {
            return jsonRpcError(null, -32700, 'Parse error: Invalid JSON')
        }

        const wasArray = Array.isArray(body)
        const messages: JsonRpcMessage[] = wasArray ? (body as JsonRpcMessage[]) : [body as JsonRpcMessage]

        if (messages.length > MAX_BATCH_SIZE) {
            return jsonRpcError(null, -32600, 'Batch too large')
        }

        const requests = messages.filter(isRequest)
        if (requests.length === 0) {
            return new Response(null, { status: 202 })
        }

        const needsState = requests.some((r) => isTrackedMethod(r.method))
        const state = needsState ? await this.stateResolver.resolve(props) : undefined

        if (!wasArray && requests.length === 1) {
            const result = await this._dispatch(requests[0]!, props, state)
            return new Response(JSON.stringify(result), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
        }

        const results = await Promise.all(requests.map((r) => this._dispatch(r, props, state)))
        return new Response(JSON.stringify(results), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
        })
    }

    private async _dispatch(
        request: JsonRpcRequest,
        props: RequestProperties,
        state: ResolvedState | undefined
    ): Promise<{ jsonrpc: '2.0'; id: number | string; result?: unknown; error?: unknown }> {
        const { id, method, params } = request

        try {
            switch (method) {
                case 'initialize':
                case 'tools/list':
                case 'tools/call':
                    return await this._dispatchTracked(request, props, state!)
                case 'resources/list':
                    return { jsonrpc: '2.0', id, result: this.resourceCatalog.getResourcesList() }
                case 'resources/read':
                    return { jsonrpc: '2.0', id, result: this.resourceCatalog.readResource(params) }
                case 'prompts/list':
                    return { jsonrpc: '2.0', id, result: this.resourceCatalog.getPromptsList() }
                case 'prompts/get':
                    return { jsonrpc: '2.0', id, result: this.resourceCatalog.getPrompt(params) }
                case 'ping':
                    return { jsonrpc: '2.0', id, result: {} }
                default:
                    return { jsonrpc: '2.0', id, error: { code: -32601, message: 'Method not found' } }
            }
        } catch (error) {
            console.error('[McpDispatcher] Internal error:', error)
            return { jsonrpc: '2.0', id, error: { code: -32603, message: 'Internal error' } }
        }
    }

    private async _dispatchTracked(
        request: JsonRpcRequest,
        props: RequestProperties,
        state: ResolvedState
    ): Promise<{ jsonrpc: '2.0'; id: number | string; result?: unknown; error?: unknown }> {
        const { id, method } = request

        try {
            const handlers = this._buildHandlerCallbacks()

            if (this.analyticsBridge.available) {
                const result = await this.analyticsBridge.dispatchThroughAnalytics(request, props, state, handlers)
                return { jsonrpc: '2.0', id, result }
            }

            switch (method) {
                case 'initialize':
                    return { jsonrpc: '2.0', id, result: await handlers.handleInitialize(request.params, props, state) }
                case 'tools/list':
                    return { jsonrpc: '2.0', id, result: await handlers.handleToolsList(state, props) }
                case 'tools/call':
                    return { jsonrpc: '2.0', id, result: await handlers.handleToolCall(request.params, props, state) }
                default:
                    return { jsonrpc: '2.0', id, error: { code: -32601, message: 'Method not found' } }
            }
        } catch (error) {
            console.error('[McpDispatcher] Tracked dispatch error:', error)
            return { jsonrpc: '2.0', id, error: { code: -32603, message: 'Internal error' } }
        }
    }

    private _buildHandlerCallbacks(): MethodHandlerCallbacks {
        return {
            handleInitialize: (params, props, state) => this._handleInitialize(params, props, state),
            handleToolsList: (state, props) => this.toolExecutor.handleToolsList(state, props),
            handleToolCall: (params, props, state) => this.toolExecutor.handleToolCall(params, props, state),
        }
    }

    private async _handleInitialize(
        params: Record<string, unknown> | undefined,
        props: RequestProperties,
        state: ResolvedState
    ): Promise<unknown> {
        const requestedVersion = (params?.protocolVersion as string) ?? LATEST_PROTOCOL_VERSION
        const protocolVersion = SUPPORTED_PROTOCOL_VERSIONS.includes(requestedVersion)
            ? requestedVersion
            : LATEST_PROTOCOL_VERSION

        const instructions = await this.instructionsBuilder.build(props, state)

        initDurationSeconds.observe(props.requestStartTime ? (Date.now() - props.requestStartTime) / 1000 : 0)

        void this.analyticsBridge.trackInitEvent(props, state)

        return {
            protocolVersion,
            capabilities: {
                tools: { listChanged: false },
                resources: { listChanged: false },
                prompts: { listChanged: false },
            },
            serverInfo: { name: 'PostHog', version: '1.0.0' },
            ...(instructions ? { instructions } : {}),
        }
    }
}
